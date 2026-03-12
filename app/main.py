"""
支払依頼書チェックツール - FastAPIメインアプリケーション
"""
import sys
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
    # データベース初期化
    init_database()
    print("データベースを初期化しました")
    print("#######################################################")
    print("###        起動確認: バージョンチェック OK          ###")
    print("#######################################################")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインページ"""
    return templates.TemplateResponse("index.html", {"request": request})


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
