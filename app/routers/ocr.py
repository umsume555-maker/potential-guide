# app/routers/ocr.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
from pathlib import Path
import os
import shutil
import zipfile

from infra.database import DB_PATH
from domain.services.invoice_match_service import InvoiceMatchService
from domain.services.excel_exporter import ExcelExporter

router = APIRouter(
    prefix="/api/ocr",
    tags=["OCR"]
)

# レスポンスモデル
class OCRResultItem(BaseModel):
    approval_no: Optional[str]
    file_name: Optional[str]
    detected_amount: Optional[int]
    detected_invoice_no: Optional[str]
    detected_date: Optional[str]
    confidence: Optional[float]
    match_status: Optional[str]
    amount_diff: Optional[int]
    
    # 申請データ（突合相手）
    vendor_name: Optional[str]
    payment_amount: Optional[int]
    
    # メタデータ
    ocr_method: Optional[str]
    has_reduced_tax: Optional[int]
    has_ringi: Optional[int]
    status: Optional[str]

class OCRAnalysisResponse(BaseModel):
    message: str
    run_id: str

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_invoices(background_tasks: BackgroundTasks, resume: bool = False):
    """OCR解析と突合を実行（バックグラウンド処理）
    
    Args:
        resume: Trueの場合、既存データを削除せず続きから再開
    """
    
    # 最新の run_id を取得
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=400, detail="No run data found. Please run payment check first.")
    
    # 既存の結果をクリア（再実行時用 - resume=Falseの場合のみ）
    if not resume:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM invoice_ocr_results")
                conn.commit()
        except Exception as e:
            print(f"[WARN] Failed to clear previous results: {e}")

    # ZIPパス設定
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    zip_in_path = base_dir / "invoice_ocr" / "ZIP_FILE_IN"
    zip_out_path = base_dir / "invoice_ocr" / "ZIP_FILE_OUT"
    
    # 1. ZIPファイルの展開と削除 (ZIP_FILE_IN -> ZIP_FILE_OUT)
    if zip_in_path.exists():
        zip_files = list(zip_in_path.glob("*.zip"))
        if zip_files:
            print(f"[INFO] Found {len(zip_files)} ZIP files in {zip_in_path}, extracting...")
            
            # 出力先ディレクトリ作成（既存があれば削除して作り直し）
            if zip_out_path.exists():
                try:
                    shutil.rmtree(zip_out_path)
                    print(f"[INFO] Cleared output directory: {zip_out_path}")
                except Exception as e:
                    print(f"[WARN] Failed to clear output directory: {e}")
            
            zip_out_path.mkdir(parents=True, exist_ok=True)
            
            for zip_file in zip_files:
                try:
                    # 展開 (CP932対応: Windowsで作成されたZIP対策)
                    with zipfile.ZipFile(zip_file, 'r') as zf:
                        for info in zf.infolist():
                            try:
                                # 文字化け対策: 多段階デコード試行
                                # Windows ZIPは通常 cp932 だが、ツールによっては UTF-8 (フラグなし) の場合もある
                                # まずバイト列に戻す
                                raw_filename = info.filename.encode('cp437')
                                
                                try:
                                    # 1. UTF-8 で試す (strict: 正しいUTF-8ならエラーにならないはず)
                                    info.filename = raw_filename.decode('utf-8')
                                except UnicodeDecodeError:
                                    # 2. CP932 で試す (replace: 一部壊れていても強行して読める部分だけ読む)
                                    # ログ解析の結果、Shift-JISと思われるが一部バイトが不正なケースがあるため
                                    info.filename = raw_filename.decode('cp932', errors='replace')
                            except Exception:
                                # encode('cp437') 自体が失敗した場合は何もしない
                                pass
                            
                            zf.extract(info, path=str(zip_out_path))

                    print(f"[INFO] Extracted: {zip_file.name}")
                    
                    # 削除
                    os.remove(zip_file)
                    print(f"[INFO] Deleted: {zip_file.name}")
                except Exception as e:
                    print(f"[ERROR] Failed to process {zip_file.name}: {e}")
    
    if not zip_out_path.exists():
        raise HTTPException(status_code=404, detail=f"Invoice directory not found: {zip_out_path}")
    
    # ファイル存在チェック
    # サブディレクトリを含めてファイルが1つでもあるか確認
    has_files = False
    for _ in zip_out_path.rglob("*"):
        if _.is_file():
            has_files = True
            break
            
    if not has_files:
        raise HTTPException(
            status_code=404, 
            detail="データが見つかりません。invoice_ocr/ZIP_FILE_IN にZIPファイルを配置し、展開を行ってください。"
        )
    
    # バックグラウンドで実行
    service = InvoiceMatchService(DB_PATH)
    background_tasks.add_task(service.process_and_match, run_id, zip_out_path)
    
    return {"message": "OCR analysis started in background", "run_id": run_id}

@router.get("/progress")
async def get_ocr_progress():
    """現在のOCR進捗状況（処理済み件数）を取得"""
    run_id = _get_latest_run_id()
    if not run_id:
        return {
            "status": "idle",
            "processed": 0,
            "total": 0,
            "message": "実行履歴がありません"
        }
        
    with sqlite3.connect(DB_PATH) as conn:
        # run_logからステータス、総件数、開始・終了時間を取得
        cursor = conn.execute(
            "SELECT status, input_rows, started_at, ended_at FROM run_log WHERE run_id = ?", 
            (run_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {
                "status": "idle",
                "processed": 0,
                "total": 0,
                "processed_time": "0s", # 追加
                "message": "実行履歴がありません"
            }
        
        status, total = row[0], row[1] or 0
        started_at_str, ended_at_str = row[2], row[3]
        
        # 処理時間計算
        from datetime import datetime
        duration_str = "0s"
        try:
            if started_at_str:
                start_dt = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S")
                if ended_at_str:
                    end_dt = datetime.strptime(ended_at_str, "%Y-%m-%d %H:%M:%S")
                    delta = end_dt - start_dt
                else:
                    delta = datetime.now() - start_dt
                
                # 分秒表示
                total_seconds = int(delta.total_seconds())
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        except Exception:
            pass

        # statusを小文字に変換（DBには大文字で保存されている場合がある）
        if status:
            status = status.lower()
        else:
            status = "idle"
        
        # 処理済み件数を取得
        cursor = conn.execute(
            "SELECT count(*) FROM invoice_ocr_results WHERE run_id = ?", 
            (run_id,)
        )
        processed = cursor.fetchone()[0]
        
        # totalが0の場合はprocessedを使用（完了済みの場合）
        if total == 0 and processed > 0:
            total = processed
        
    # メッセージ生成
    if status == "completed":
        message = f"完了しました！処理件数: {processed}件 ({duration_str})"
    elif status == "error":
        message = "エラーが発生しました"
    elif status == "running":
        message = f"処理中... {processed}/{total}件 ({duration_str})"
    else:
        message = "待機中"
        
    return {
        "status": status,
        "processed": processed,
        "total": total,
        "processed_time": duration_str, # 追加
        "message": message
    }

@router.get("/results", response_model=List[OCRResultItem])
async def get_ocr_results(status: Optional[str] = None):
    """OCR突合結果を取得"""
    run_id = _get_latest_run_id()
    if not run_id:
        return []
        
    query = """
        SELECT 
            r.approval_no, r.file_name, r.detected_amount, r.detected_invoice_no,
            r.detected_date,
            r.confidence, r.match_status, r.amount_diff, r.ocr_method, 
            r.has_reduced_tax, r.has_ringi, s.status,
            s.vendor_name, s.payment_amount
        FROM invoice_ocr_results r
        LEFT JOIN output_summary s 
            ON r.run_id = s.run_id 
            AND r.approval_no = s.decision_no
        WHERE r.run_id = ?
    """
    params = [run_id]
    
    if status:
        query += " AND r.match_status = ?"
        params.append(status)
        
    query += " ORDER BY r.match_status DESC, r.approval_no" # NG/WARNING first
    
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        for row in cursor.fetchall():
            results.append({
                "approval_no": row["approval_no"],
                "file_name": row["file_name"],
                "detected_amount": row["detected_amount"],
                "detected_invoice_no": row["detected_invoice_no"],
                "detected_date": row["detected_date"],
                "confidence": row["confidence"],
                "match_status": row["match_status"],
                "amount_diff": row["amount_diff"],
                "ocr_method": row["ocr_method"],
                "has_reduced_tax": row["has_reduced_tax"],
                "has_ringi": row["has_ringi"],
                "status": row["status"],
                "vendor_name": row["vendor_name"],
                "payment_amount": row["payment_amount"]
            })
            
    return results

@router.get("/export")
async def export_excel():
    """OCR結果をExcelでダウンロード"""
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=400, detail="No run data found")
        
    exporter = ExcelExporter(DB_PATH)
    output = exporter.export_ocr_results(run_id)
    
    filename = f"ocr_results_{run_id}.xlsx"
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/files/{filename}")
async def get_invoice_file(filename: str):
    """PDF/画像ファイルを返す"""
    # ファイル検索（ZIP_FILE_OUT以下のどこかにあるはず）
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    search_root = base_dir / "invoice_ocr" / "ZIP_FILE_OUT"
    
    # セキュリティ: ファイル名にパス区切りを含ませない
    if "/" in filename or "\\" in filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    # 再帰的に検索
    found_path = None
    for path in search_root.rglob(filename):
        found_path = path
        break
        
    if not found_path or not found_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(found_path, filename=filename, content_disposition_type="inline")

def _get_latest_run_id():
    """最新の実行IDを取得（TEST含む）"""
    with sqlite3.connect(DB_PATH) as conn:
        # TEST優先
        cursor = conn.execute("SELECT run_id FROM run_log WHERE run_id LIKE 'TEST_%' ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row: return row[0]
        
        cursor = conn.execute("SELECT run_id FROM run_log ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
