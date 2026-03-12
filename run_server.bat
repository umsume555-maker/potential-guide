@echo off
chcp 65001 > nul
cd /d %~dp0
echo ==========================================
echo   支払依頼書チェックツール - 起動
echo ==========================================
echo.

echo [1] 依存ライブラリを確認中...
py -m pip install fastapi uvicorn openpyxl python-multipart jinja2 gspread oauth2client --quiet

echo [2] キャッシュをクリア中...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo [3] ブラウザを開きます...
timeout /t 2 > nul
start http://127.0.0.1:8000

echo [4] サーバーを起動します...
echo     ログは server.log に保存されます
echo.
py -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=False)" > server.log 2>&1

pause
