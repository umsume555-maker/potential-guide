"""
チェック実行API
"""
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.services.check_service import CheckService, CheckResult
from domain.services.cumulative_service import CumulativeService
from infra.database import get_db, resolve_credentials_path
from infra.settings_repository import SettingsRepository
from infra.spreadsheet_service_ext import SpreadsheetServiceExt

router = APIRouter(prefix="/api/check", tags=["check"])
_settings_repo = SettingsRepository()

# 最後の実行結果を保持
last_result: Optional[CheckResult] = None


class CheckRequest(BaseModel):
    """チェックリクエスト"""
    base_month: str


class CheckResponse(BaseModel):
    """チェックレスポンス"""
    run_id: str
    base_month: str
    status: str
    input_rows: int
    output_rows: int
    ng_count: int
    hold_count: int
    dash_count: int
    excel_filename: Optional[str] = None
    error_message: Optional[str] = None
    # 正マスター情報
    rule_total: Optional[int] = 0
    rule_updated: Optional[str] = None
    rule_db_path: Optional[str] = None


@router.post("/run", response_model=CheckResponse)
async def run_check(
    base_month: str = Form(...),
    csv_file: UploadFile = File(...)
):
    """
    チェック実行
    
    - base_month: 基準月 (YYYY-MM)
    - csv_file: 入力CSVファイル
    """
    global last_result
    
    # 基準月のバリデーション
    try:
        datetime.strptime(base_month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="基準月の形式が不正です。YYYY-MM形式で入力してください。"
        )
    
    # 一時ファイルにCSVを保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await csv_file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        # 出力ディレクトリ
        output_dir = Path(__file__).parent.parent.parent / "data"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # チェック実行
        service = CheckService()
        result = service.run_check(tmp_path, base_month, output_dir)
        last_result = result
        
        return CheckResponse(
            run_id=result.run_id,
            base_month=result.base_month,
            status=result.status,
            input_rows=result.input_rows,
            output_rows=result.output_rows,
            ng_count=result.ng_count,
            hold_count=result.hold_count,
            dash_count=result.dash_count,
            excel_filename=result.excel_path.name if result.excel_path else None,
            error_message=result.error_message,
            rule_total=result.rule_total,
            rule_updated=result.rule_updated,
            rule_db_path=result.rule_db_path
        )
    
    finally:
        # 一時ファイル削除
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/status")
async def get_status():
    """最後のチェック結果を取得"""
    if last_result is None:
        return {"status": "no_run", "message": "まだチェックが実行されていません"}
    
    return {
        "status": last_result.status,
        "run_id": last_result.run_id,
        "base_month": last_result.base_month,
        "input_rows": last_result.input_rows,
        "output_rows": last_result.output_rows,
        "ng_count": last_result.ng_count,
        "hold_count": last_result.hold_count,
        "dash_count": last_result.dash_count,
        "excel_filename": last_result.excel_path.name if last_result.excel_path else None,
    }


@router.get("/download/{filename}")
async def download_excel(filename: str):
    """Excelファイルをダウンロード"""
    if "/" in filename or "\\" in filename or ".." in filename or not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    output_dir = Path(__file__).parent.parent.parent / "data"
    file_path = output_dir / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    
    # 拡張子強制付与（レスポンス用）
    dl_filename = filename if filename.lower().endswith(".xlsx") else f"{filename}.xlsx"
    
    return FileResponse(
        path=file_path,
        filename=dl_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class MonthlyUpdateRequest(BaseModel):
    run_id: str
    base_month: str


@router.post("/monthly-update")
async def update_monthly(data: MonthlyUpdateRequest):
    """
    月次更新を実行
    - チェック結果(OK)を累積に追加
    - 古い累積を削除
    """
    try:
        service = CumulativeService()
        count = service.update_monthly(data.run_id, data.base_month)

        message = f"月次更新が完了しました（追加: {count}件）"

        # 現場案内用シートから、対象月が今回閉じる基準月以前の
        # 請求一覧突合系の古い「もれ」等をまとめて削除する
        try:
            with get_db() as conn:
                site_sheet_id = _settings_repo.get_setting(conn, "site_sheet_id")
            if site_sheet_id:
                with get_db() as conn:
                    creds_setting = _settings_repo.get_setting(conn, "google_credentials_path")
                creds_path = resolve_credentials_path(creds_setting)
                if creds_path:
                    ext_service = SpreadsheetServiceExt(credentials_path=str(creds_path))
                    purge_log = ext_service.purge_old_reconcile_rows(site_sheet_id, data.base_month)
                    if purge_log.get("updated"):
                        message += f" / 現場シートの古い「もれ」等を{purge_log.get('rows_removed', 0)}件削除しました"
        except Exception as e:
            # シート側の後片付けが失敗しても月次更新自体は成功させる
            message += f" / 現場シートの整理はスキップされました（{e}）"

        return {
            "status": "ok",
            "message": message,
            "count": count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"月次更新エラー: {str(e)}")
