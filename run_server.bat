@echo off
chcp 65001 > nul
cd /d %~dp0
echo ==========================================
echo   支払依頼書チェックツール - 起動
echo ==========================================
echo.

echo [1] 既存サーバーを停止中 (port 8000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
    echo     PID %%a を停止します
    taskkill /F /PID %%a > nul 2>&1
)
timeout /t 1 > nul

echo [2] キャッシュをクリア中...
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo [3] 依存ライブラリを確認中...
py -m pip install -r requirements.txt --quiet

echo [4] 環境変数を設定中...
set GOOGLE_APPLICATION_CREDENTIALS=%~dp0data\credentials.json
echo     GOOGLE_APPLICATION_CREDENTIALS=%GOOGLE_APPLICATION_CREDENTIALS%

echo [5] ブラウザを開きます...
timeout /t 2 > nul
start http://127.0.0.1:8000

echo [6] サーバーを起動します...
echo     ログは server.log に保存されます
echo.
echo === 起動: %DATE% %TIME% === >> server.log
py -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, reload=False)" >> server.log 2>&1

pause
