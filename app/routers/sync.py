
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.database import DB_PATH, get_db, resolve_credentials_path
from infra.settings_repository import SettingsRepository
from infra.spreadsheet_service import SpreadsheetService

router = APIRouter(prefix="/api/sync", tags=["sync"])
repo = SettingsRepository()

class SpreadsheetSyncRequest(BaseModel):
    run_id: str
    spreadsheet_id: str
    upload_drive: bool = False

@router.post("/google-sheet")
async def sync_google_sheet(data: SpreadsheetSyncRequest):
    """Googleスプレッドシートにデータを同期"""
    import time
    import sys
    try:
        print(f"[DEBUG] Using SpreadsheetService from: {sys.modules['infra.spreadsheet_service'].__file__}")
    except:
        pass
    start_time = time.time()
    
    def log_step(msg):
        elapsed = time.time() - start_time
        print(f"[SHEET SYNC DEBUG] {elapsed:.2f}s - {msg}")
    
    log_step(f"Start sync_google_sheet (DriveUpload={data.upload_drive})")
    
    try:
        with get_db() as conn:
            stored = repo.get_setting(conn, "google_credentials_path")

        log_step(f"Credentials path from DB: {stored}")

        creds = resolve_credentials_path(stored)
        log_step(f"Resolved credentials path: {creds}")

        if not creds:
            raise HTTPException(status_code=400, detail="認証ファイル(credentials.json)が見つかりません。data/credentials.json に配置するか、設定タブからアップロードしてください。")

        creds_path = str(creds)

        log_step("Creating SpreadsheetService...")
        service = SpreadsheetService(credentials_path=creds_path)
        
        log_step(f"Starting sync_to_sheet for run_id={data.run_id}, spreadsheet_id={data.spreadsheet_id}")
        count = service.sync_to_sheet(str(DB_PATH), data.run_id, data.spreadsheet_id, upload_drive=data.upload_drive)
        log_step(f"sync_to_sheet complete: {count} rows")
        
        message = f"経理用シート更新: {count}行"
        
        # 現場用シート更新 (B案を有効化: Sync時にリセットをかけるため)
        # 理由: チェック実行直後(Reconcile未実行)の場合、DBには「もれ」データが存在しない。
        # この状態でSyncすることで現場シートを上書きし、前月の「もれ」データをクリア(リセット)できる。
        with get_db() as conn:
            site_sheet_id = repo.get_setting(conn, "site_sheet_id")
            
        log_step(f"Site sheet ID: {site_sheet_id}")
        
        if site_sheet_id:
            try:
                log_step("Starting sync_site_sheet (Reset Mode)...")
                # 現場更新 (部門フィルタなし)
                site_log = service.sync_site_sheet(str(DB_PATH), data.run_id, site_sheet_id)
                log_step(f"sync_site_sheet complete: {site_log}")
                
                if site_log.get("updated"):
                    message += f"\n現場用シート更新: {site_log.get('rows_written', 0)}行"
                else:
                    reason = site_log.get("reason", "Unknown")
                    print(f"Site sheet skipped: {reason}")
                    
                if site_log.get("status") == "error":
                        message += f"\n現場用エラー: {site_log.get('error')}"
            except Exception as ex:
                print(f"Site sync fatal error: {ex}")
                message += f"\n現場用更新失敗: {ex}"

        log_step("Sync complete, returning response")
        return {
            "status": "ok", 
            "message": message
        }
    except FileNotFoundError as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"FileNotFoundError: {str(e)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"同期エラー: {type(e).__name__}: {str(e)}")
