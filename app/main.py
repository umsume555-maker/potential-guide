"""
支払依頼書チェックツール - FastAPIメインアプリケーション
"""
import sys
import logging
import time
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.routers import check, master, rule, assignment, exclude, sync, settings, ocr, reconcile
from infra.database import init_database

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 起動時のキャッシュバスター（サーバー再起動のたびに新しい値になる）
STATIC_VER = str(int(time.time()))

# アプリケーション作成
app = FastAPI(
    title="支払依頼書チェックツール",
    description="E2出力の支払依頼書CSVを取り込み、判定・照合・出力を行うツール",
    version="1.0.0"
)

# 静的ファイルとテンプレート
ui_dir = project_root / "ui"
app.mount("/static", StaticFiles(directory=ui_dir / "static"), name="static")
templates = Jinja2Templates(directory=ui_dir / "templates")

# ルーター登録
app.include_router(check.router)
app.include_router(master.router)
app.include_router(rule.router)
app.include_router(assignment.router)
app.include_router(exclude.router)
app.include_router(sync.router)
app.include_router(settings.router)
app.include_router(ocr.router)
app.include_router(reconcile.router)


@app.on_event("startup")
async def startup_event():
    """起動時の初期化"""
    init_database()
    logger.info("データベースを初期化しました")
    logger.info("=" * 55)
    logger.info("  起動確認: バージョンチェック OK")
    logger.info("=" * 55)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインページ"""
    return templates.TemplateResponse("index.html", {"request": request, "static_ver": STATIC_VER})


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


@app.get("/debug/creds")
async def debug_creds():
    """認証ファイル診断（一時エンドポイント）"""
    import sqlite3
    from infra.database import DATA_DIR, resolve_credentials_path, CREDENTIALS_PATH
    db_path = DATA_DIR / "payment_check.db"
    conn = sqlite3.connect(str(db_path))
    stored = conn.execute("SELECT value FROM app_settings WHERE key='google_credentials_path'").fetchone()
    conn.close()
    stored_val = stored[0] if stored else None
    resolved = resolve_credentials_path(stored_val)
    return {
        "db_stored": stored_val,
        "resolved_path": str(resolved) if resolved else None,
        "canonical_exists": CREDENTIALS_PATH.exists(),
        "canonical_path": str(CREDENTIALS_PATH),
        "sync_py_has_resolve": "resolve_credentials_path" in open("app/routers/sync.py", encoding="utf-8").read(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
