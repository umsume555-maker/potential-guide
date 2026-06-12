# app/routers/ocr.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, File, UploadFile, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
from pathlib import Path
import os
import shutil
import zipfile
import threading

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
    skip_count: int = 0
    process_count: int = 0

# ──────────────────────────────────────────
# ZIP差分解析 ヘルパー関数
# ──────────────────────────────────────────

EFS_FLAG = 0x800  # ZIP仕様: General purpose bit 11 = EFS(UTF-8)

def _decode_zip_filename(info) -> str:
    """ZIPエントリのファイル名を正しくデコード"""
    fname = info.filename
    if not (info.flag_bits & EFS_FLAG):
        try:
            raw = fname.encode('cp437')
            decoded = None
            for enc in ('cp932', 'utf-8'):
                try:
                    decoded = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if decoded is None:
                decoded = raw.decode('cp932', errors='ignore')
            return decoded
        except Exception:
            pass
    return fname


def _list_zip_approval_nos(zip_path: Path) -> list:
    """ZIPを展開せずにトップレベルフォルダ名（=承認番号）一覧を返す"""
    approval_nos = set()
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                fname = _decode_zip_filename(info)
                parts = fname.strip('/').split('/')
                if parts[0]:
                    approval_nos.add(parts[0])
    except Exception as e:
        print(f"[WARN] _list_zip_approval_nos error ({zip_path.name}): {e}")
    return list(approval_nos)


def _get_zip_log() -> dict:
    """{zip_filename: zip_size} を ocr_zip_log から取得"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ocr_zip_log (
                    zip_filename TEXT PRIMARY KEY,
                    zip_size     INTEGER NOT NULL,
                    processed_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            cursor = conn.execute("SELECT zip_filename, zip_size FROM ocr_zip_log")
            return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception as e:
        print(f"[WARN] _get_zip_log error: {e}")
        return {}


def _update_zip_log(process_zip_files: list):
    """処理済みZIPを ocr_zip_log に記録・更新"""
    if not process_zip_files:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO ocr_zip_log (zip_filename, zip_size, processed_at)
                VALUES (?, ?, datetime('now', 'localtime'))
            """, [(zf.name, zf.stat().st_size) for zf in process_zip_files if zf.exists()])
            conn.commit()
        print(f"[INFO] ocr_zip_log 更新: {len(process_zip_files)} 件")
    except Exception as e:
        print(f"[WARN] _update_zip_log error: {e}")


def _copy_results_for_skip_zips(run_id: str, skip_approval_nos: list):
    """スキップZIPの承認番号の結果を前回runから現在run_idにコピー"""
    if not skip_approval_nos:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            placeholders = ','.join('?' * len(skip_approval_nos))
            # 前回結果を持つrun_idを取得
            cursor = conn.execute(f"""
                SELECT run_id FROM invoice_ocr_results
                WHERE approval_no IN ({placeholders})
                  AND run_id != ?
                ORDER BY rowid DESC
                LIMIT 1
            """, skip_approval_nos + [run_id])
            row = cursor.fetchone()
            if not row:
                print(f"[INFO] スキップZIPの前回結果なし（初回実行）")
                return
            prev_run_id = row[0]

            # 前回結果を現在のrun_idにコピー（既存は上書きしない）
            cursor = conn.execute(f"""
                SELECT approval_no, file_name, dept_code, dept_name,
                       vendor_code, vendor_name, target_decision_no,
                       detected_amount, detected_invoice_no, detected_date,
                       has_reduced_tax, has_ringi, status, confidence,
                       ocr_method, match_status, amount_diff
                FROM invoice_ocr_results
                WHERE run_id = ? AND approval_no IN ({placeholders})
            """, [prev_run_id] + skip_approval_nos)

            rows = cursor.fetchall()
            conn.executemany("""
                INSERT OR IGNORE INTO invoice_ocr_results (
                    run_id, approval_no, file_name, dept_code, dept_name,
                    vendor_code, vendor_name, target_decision_no,
                    detected_amount, detected_invoice_no, detected_date,
                    has_reduced_tax, has_ringi, status, confidence,
                    ocr_method, match_status, amount_diff
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [[run_id] + list(r) for r in rows])
            conn.commit()
            print(f"[INFO] スキップ結果コピー: {len(rows)} 件 (from {prev_run_id})")
    except Exception as e:
        print(f"[WARN] _copy_results_for_skip_zips error: {e}")


def _safe_rmtree(target: Path):
    """PermissionErrorを無視しながらフォルダを削除（使用中ファイルはスキップ）"""
    skipped = 0
    for item in sorted(target.rglob("*"), reverse=True):
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        except PermissionError:
            skipped += 1
            print(f"[WARN] 使用中のためスキップ: {item.name}")
        except Exception as e:
            skipped += 1
            print(f"[WARN] 削除失敗 ({type(e).__name__}): {item.name}")
    try:
        target.rmdir()
    except Exception:
        pass
    if skipped:
        print(f"[WARN] スキップしたファイル数: {skipped} 件（使用中のため）")


def _archive_extracted_files(zip_out_path: Path, archive_path: Path, zip_file: Path):
    """ZIP展開後のファイルを PDF_ARCHIVE に永続コピー（承認番号フォルダごと）

    zip_out_path にある承認番号フォルダを archive_path にコピーする。
    zip_file はコピー対象フォルダを特定するために使用（展開直後・削除前に呼ぶこと）。
    """
    try:
        # ZIPに含まれる承認番号一覧を取得し、そのフォルダのみアーカイブ対象とする
        approval_nos = set(_list_zip_approval_nos(zip_file)) if zip_file.exists() else set()
        if not approval_nos:
            # ZIP情報が取れない場合は zip_out_path 直下フォルダを全てコピー
            approval_nos = {d.name for d in zip_out_path.iterdir() if d.is_dir()}

        copied = 0
        for approval_no in approval_nos:
            approval_dir = zip_out_path / approval_no
            if not approval_dir.exists():
                continue
            dest_dir = archive_path / approval_no
            dest_dir.mkdir(parents=True, exist_ok=True)
            for src_file in approval_dir.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(approval_dir)
                    dest_file = dest_dir / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(src_file, dest_file)
                        copied += 1
                    except Exception as ce:
                        print(f"[WARN] archive copy failed: {src_file.name} - {ce}")
        print(f"[INFO] PDF_ARCHIVE コピー完了: {copied} ファイル ({len(approval_nos)} 承認番号)")
    except Exception as e:
        print(f"[WARN] _archive_extracted_files error: {e}")


def _extract_zip(zip_file: Path, out_path: Path):
    """ZIPを out_path に展開（文字コード対応）"""
    extracted = 0
    failed = 0
    try:
        with zipfile.ZipFile(zip_file, 'r') as zf:
            for info in zf.infolist():
                info.filename = _decode_zip_filename(info)
                try:
                    zf.extract(info, path=str(out_path))
                    extracted += 1
                except Exception as fe:
                    failed += 1
                    print(f"[WARN] Skip file in {zip_file.name}: {ascii(info.filename)} ({type(fe).__name__})")
        print(f"[INFO] Extracted: {zip_file.name} (ok={extracted}, skip={failed})")
    except Exception as e:
        print(f"[ERROR] Failed to extract {zip_file.name}: {type(e).__name__}: {ascii(str(e))}")


# ──────────────────────────────────────────

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_invoices(
    background_tasks: BackgroundTasks,
    resume: bool = False,
    fast: bool = False,
    files: Optional[List[UploadFile]] = File(None)
):
    """OCR解析と突合を実行（差分解析対応・バックグラウンド処理）

    Args:
        resume: Trueの場合、既存データを削除せず続きから再開
        fast: Trueの場合、Geminiによる傾き補正をスキップして高速化
        files: ZIPファイル（複数可）（ブラウザからアップロード、省略時はZIP_FILE_INの既存ファイルを使用）
    """

    # 最新の run_id を取得
    run_id = _get_latest_run_id()
    if not run_id:
        raise HTTPException(status_code=400, detail="No run data found. Please run payment check first.")

    # ZIPパス設定
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    zip_in_path = base_dir / "invoice_ocr" / "ZIP_FILE_IN"
    zip_out_path = base_dir / "invoice_ocr" / "ZIP_FILE_OUT"

    # 0. ブラウザからアップロードされたZIPをZIP_FILE_INに保存（複数対応）
    uploaded = [f for f in (files or []) if f and f.filename]
    if uploaded:
        zip_in_path.mkdir(parents=True, exist_ok=True)
        for old_zip in zip_in_path.glob("*.zip"):
            old_zip.unlink()
        for file in uploaded:
            if not file.filename.lower().endswith(".zip"):
                raise HTTPException(status_code=400, detail=f"ZIPファイル(.zip)のみアップロード可能です: {file.filename}")
            save_path = zip_in_path / file.filename
            content = await file.read()
            with open(save_path, "wb") as f:
                f.write(content)
            print(f"[INFO] ZIP uploaded: {file.filename} ({len(content):,} bytes)")
        print(f"[INFO] 合計 {len(uploaded)} 件のZIPをアップロードしました")

    # 1. ZIP_FILE_IN のZIPファイル一覧を取得
    zip_files = list(zip_in_path.glob("*.zip")) if zip_in_path.exists() else []
    if not zip_files and not zip_out_path.exists():
        raise HTTPException(status_code=404, detail="ZIPファイルが見つかりません。")

    # 2. 差分判定（ファイル名＋サイズで比較）
    zip_log = _get_zip_log()
    skip_zips = []    # 変更なし → スキップ
    process_zips = [] # 新規 or サイズ変更 → OCR実行

    for zf in zip_files:
        logged_size = zip_log.get(zf.name)
        if logged_size is not None and logged_size == zf.stat().st_size:
            skip_zips.append(zf)
        else:
            process_zips.append(zf)

    skip_count = len(skip_zips)
    process_count = len(process_zips)
    print(f"[INFO] 差分判定: スキップ={skip_count}件, 処理={process_count}件")

    # PDF永続アーカイブパス（OCR解析実行時に削除されない永続保管場所）
    pdf_archive_path = base_dir / "invoice_ocr" / "PDF_ARCHIVE"

    # 3. ZIP_FILE_OUT の準備
    # - 処理対象ZIPのみ展開（スキップZIPの既存ファイルは保持）
    # - resume=False かつ全件処理の場合は ZIP_FILE_OUT をクリア
    if not resume:
        if skip_count == 0:
            # 全件新規/変更 → ZIP_FILE_OUT を全クリア & 全結果クリア
            if zip_out_path.exists():
                try:
                    shutil.rmtree(zip_out_path)
                    print(f"[INFO] ZIP_FILE_OUT クリア（全件再処理）")
                except PermissionError as e:
                    # ファイルが別プロセスに使用中の場合は個別削除にフォールバック
                    print(f"[WARN] rmtree失敗（使用中ファイルあり）、個別削除に切り替え: {e}")
                    _safe_rmtree(zip_out_path)
                    print(f"[INFO] ZIP_FILE_OUT 個別削除完了")
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM invoice_ocr_results")
                conn.commit()
                print(f"[INFO] invoice_ocr_results クリア（全件再処理）")
        else:
            # 差分あり → ZIP_FILE_OUT は保持、スキップZIPの結果をコピー
            # スキップZIPの承認番号をZIP内容から取得（展開不要）
            skip_approval_nos = []
            for zf in skip_zips:
                nos = _list_zip_approval_nos(zf)
                skip_approval_nos.extend(nos)
                print(f"[INFO] スキップ: {zf.name} ({len(nos)}フォルダ)")

            # 前回の結果を現在のrun_idにコピー
            _copy_results_for_skip_zips(run_id, skip_approval_nos)

    zip_out_path.mkdir(parents=True, exist_ok=True)
    pdf_archive_path.mkdir(parents=True, exist_ok=True)

    # 4. 処理対象ZIPのみ展開 & PDF_ARCHIVEにもコピー（永続保管）
    for zf in process_zips:
        _extract_zip(zf, zip_out_path)
        _archive_extracted_files(zip_out_path, pdf_archive_path, zf)
        os.remove(zf)
        print(f"[INFO] Deleted: {zf.name}")

    # スキップZIPも ZIP_FILE_IN から削除
    for zf in skip_zips:
        try:
            os.remove(zf)
        except Exception:
            pass

    # ZIP_FILE_OUT にファイルがあるか確認
    has_files = any(True for _ in zip_out_path.rglob("*") if _.is_file())
    if not has_files:
        raise HTTPException(
            status_code=404,
            detail="データが見つかりません。ZIPファイルを選択して再度実行してください。"
        )

    # 5. バックグラウンドでOCR実行
    import asyncio

    def _run_ocr_thread(svc, rid, zip_path, is_fast, done_zips):
        """async process_and_match をスレッド内で実行し、完了後にzip_logを更新"""
        asyncio.run(svc.process_and_match(rid, zip_path, is_fast))
        _update_zip_log(done_zips)

    service = InvoiceMatchService(DB_PATH)
    t = threading.Thread(
        target=_run_ocr_thread,
        args=(service, run_id, zip_out_path, fast, process_zips),
        daemon=True,
        name="ocr-worker"
    )
    t.start()

    mode = "差分解析" if skip_count > 0 else "全件解析"
    msg = f"{mode}開始: 新規/変更={process_count}件, スキップ={skip_count}件"
    print(f"[INFO] OCR thread started: run_id={run_id}, fast={fast}, {msg}")

    return {
        "message": msg,
        "run_id": run_id,
        "skip_count": skip_count,
        "process_count": process_count
    }

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
                "processed_time": "0s",
                "message": "実行履歴がありません"
            }

        status, total = row[0], row[1] or 0
        started_at_str, ended_at_str = row[2], row[3]

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
                total_seconds = int(delta.total_seconds())
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        except Exception:
            pass

        if status:
            status = status.lower()
        else:
            status = "idle"

        cursor = conn.execute(
            "SELECT count(*) FROM invoice_ocr_results WHERE run_id = ?",
            (run_id,)
        )
        processed = cursor.fetchone()[0]

        if total == 0 and processed > 0:
            total = processed

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
        "processed_time": duration_str,
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
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, [run_id])
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

@router.get("/files/{approval_no}/{filename}")
async def get_invoice_file_by_approval(approval_no: str, filename: str):
    """PDF/画像ファイルを承認番号指定で返す（同名ファイル対策・永続アーカイブ対応）"""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    # パストラバーサル防止
    if ".." in approval_no or "/" in approval_no or "\\" in approval_no:
        raise HTTPException(status_code=400, detail="Invalid approval_no")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    def _find_in(search_root: Path) -> Optional[Path]:
        """指定ディレクトリ内で承認番号フォルダを起点にファイルを検索"""
        if not search_root.exists():
            return None
        for path in search_root.rglob(filename):
            if approval_no in [p.name for p in path.parents]:
                return path
        return None

    # 1. まず ZIP_FILE_OUT を検索（最新のOCR結果）
    found_path = _find_in(base_dir / "invoice_ocr" / "ZIP_FILE_OUT")

    # 2. なければ PDF_ARCHIVE を検索（永続保管済みファイル）
    if not found_path:
        found_path = _find_in(base_dir / "invoice_ocr" / "PDF_ARCHIVE")
        if found_path:
            print(f"[INFO] PDF_ARCHIVEから提供: {approval_no}/{filename}")

    if not found_path or not found_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(found_path, filename=filename, content_disposition_type="inline")


@router.get("/files/{filename}")
async def get_invoice_file(filename: str):
    """PDF/画像ファイルを返す（後方互換用・旧形式）"""
    base_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    def _find_first(search_root: Path):
        if not search_root.exists():
            return None
        for path in search_root.rglob(filename):
            return path
        return None

    # ZIP_FILE_OUT → PDF_ARCHIVE の順で検索
    found_path = _find_first(base_dir / "invoice_ocr" / "ZIP_FILE_OUT")
    if not found_path:
        found_path = _find_first(base_dir / "invoice_ocr" / "PDF_ARCHIVE")

    if not found_path or not found_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(found_path, filename=filename, content_disposition_type="inline")


def _get_latest_run_id():
    """最新の実行IDを取得（TEST含む）"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT run_id FROM run_log WHERE run_id LIKE 'TEST_%' ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row: return row[0]

        cursor = conn.execute("SELECT run_id FROM run_log ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
