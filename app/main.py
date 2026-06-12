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

    # PDF_ARCHIVE内のZIPを自動展開（サーバー起動時に一度だけ実行）
    _auto_extract_archive_zips()

    logger.info("=" * 55)
    logger.info("  起動確認: バージョンチェック OK")
    logger.info("=" * 55)


def _auto_extract_archive_zips():
    """起動時: PDF_ARCHIVE内のZIPファイルを自動展開する"""
    import zipfile
    from app.routers.ocr import _extract_zip

    archive_path = project_root / "invoice_ocr" / "PDF_ARCHIVE"
    if not archive_path.exists():
        return

    zip_files = list(archive_path.glob("*.zip"))
    if not zip_files:
        return

    logger.info(f"PDF_ARCHIVE内のZIPを自動展開します: {len(zip_files)}件")
    for zf in zip_files:
        try:
            _extract_zip(zf, archive_path)
            zf.unlink()
            logger.info(f"  展開完了: {zf.name}")
        except Exception as e:
            logger.warning(f"  展開失敗: {zf.name} - {e}")
    logger.info(f"PDF_ARCHIVE 自動展開完了")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインページ"""
    return templates.TemplateResponse("index.html", {"request": request, "static_ver": STATIC_VER})


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
