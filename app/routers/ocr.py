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
    vendor_name: Optional[str]
    dept_name: Optional[str]
    status: Optional[str]
    has_ringi: Optional[int]

class OCRAnalysisResponse(BaseModel):
    message: str
    run_id: str

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_invoices(background_tasks: BackgroundTasks, resume: bool = False, fast: bool = False):
    """OCR解析と突合を実行（バックグラウンド処理）

    Args:
        resume: Trueの場合、既存データを削除せず続きから再開
        fast: Trueの場合、Geminiによる傾き補正をスキップして高速化
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
            
            EFS_FLAG = 0x800  # ZIP仕様: General purpose bit 11 = EFS(UTF-8)
            for zip_file in zip_files:
                try:
                    extracted = 0
                    failed = 0
                    with zipfile.ZipFile(zip_file, 'r') as zf:
                        for info in zf.infolist():
                            # EFSフラグが立っていなければ cp437 経由で raw bytes を取り直し、
                            # cp932 → UTF-8 の順に厳密デコード。両方失敗時は cp932(ignore)
                            # で不正バイトを捨てて展開を続行する（\ufffd を生成しない）
                            if not (info.flag_bits & EFS_FLAG):
                                try:
                                    raw = info.filename.encode('cp437')
                                except UnicodeEncodeError:
                                    raw = None

                                if raw is not None:
                                    decoded = None
                                    for enc in ('cp932', 'utf-8'):
                                        try:
                                            decoded = raw.decode(enc)
                                            break
                                        except UnicodeDecodeError:
                                            continue
                                    if decoded is None:
                                        decoded = raw.decode('cp932', errors='ignore')
                                    info.filename = decoded

                            # 個別ファイル単位で try：1ファイル失敗でも残りは展開継続
                            try:
                                zf.extract(info, path=str(zip_out_path))
                                extracted += 1
                            except Exception as fe:
                                failed += 1
                                # ファイル名は ASCII safe な repr で出力
                                print(f"[WARN] Skip file in {zip_file.name}: {ascii(info.filename)} ({type(fe).__name__})")

                    print(f"[INFO] Extracted: {zip_file.name} (ok={extracted}, skip={failed})")

                    # 削除
                    os.remove(zip_file)
                    print(f"[INFO] Deleted: {zip_file.name}")
                except Exception as e:
                    print(f"[ERROR] Failed to process {zip_file.name}: {type(e).__name__}: {ascii(str(e))}")
    
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
    background_tasks.add_task(service.process_and_match, run_id, zip_out_path, fast)
    
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
async def get_ocr_results():
    """OCR突合結果を取得"""
    run_id = _get_latest_run_id()
    if not run_id:
        return []
        
    query = """
        SELECT
            r.approval_no, r.file_name,
            r.vendor_name, r.dept_name, r.status, r.has_ringi
        FROM invoice_ocr_results r
        WHERE r.run_id = ?
        ORDER BY r.approval_no, r.file_name
    """
    params = [run_id]

    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        for row in cursor.fetchall():
            results.append({
                "approval_no": row["approval_no"],
                "file_name": row["file_name"],
                "vendor_name": row["vendor_name"],
                "dept_name": row["dept_name"],
                "status": row["status"],
                "has_ringi": row["has_ringi"],
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
