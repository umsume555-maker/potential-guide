
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.database import DB_PATH, get_db, DATA_DIR
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
        creds_path = None
        
        with get_db() as conn:
            # DBからパスを取得
            creds_path = repo.get_setting(conn, "google_credentials_path")
            
        log_step(f"Credentials path from DB: {creds_path}")
        
        # DBになくても、アプリのデータフォルダにあればそれを使う
        if not creds_path:
            default_path = DATA_DIR / "credentials.json"
            if default_path.exists():
                creds_path = str(default_path)
                log_step(f"Using default credentials: {creds_path}")

        if not creds_path:
             raise HTTPException(status_code=400, detail="認証ファイル(credentials.json)が設定されていません。設定タブからアップロードしてください。")

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
        raise HTTPException(status_code=400, detail="認証ファイルが見つかりません。再アップロードしてください。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同期エラー: {str(e)}")
