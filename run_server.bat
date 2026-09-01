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

echo [5] このPCのIPアドレスを確認中...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    set LOCAL_IP=%%a
    goto :found_ip
)
:found_ip
set LOCAL_IP=%LOCAL_IP: =%
echo     アクセスURL: http://%LOCAL_IP%:8000
echo     ※ 他のPCからは上記URLでアクセスしてください

echo [5.5] server_url.txt を更新中...
if not exist "%~dp0配布用_new" mkdir "%~dp0配布用_new"
echo http://%LOCAL_IP%:8000> "%~dp0配布用_new\server_url.txt"
echo     ローカル配布用: http://%LOCAL_IP%:8000

echo [5.6] アプリ内部のベースURL設定を更新中...
if not exist "%~dp0config" mkdir "%~dp0config"
echo http://%LOCAL_IP%:8000> "%~dp0config\server_base_url.txt"
echo     ベースURL設定: http://%LOCAL_IP%:8000

set NAS_PATH=\\Ls210d50d\経理財務共有箱\2.決算情報\配布用\server_url.txt
if exist "%NAS_PATH%" (
    echo http://%LOCAL_IP%:8000> "%NAS_PATH%"
    echo     NAS配布用も更新しました: http://%LOCAL_IP%:8000
) else (
    echo     NAS配布用フォルダは見つかりませんでした（スキップ）
)

echo [6] ブラウザを開きます...
timeout /t 2 > nul
start http://127.0.0.1:8000

echo [7] サーバーを起動します (社内LAN全体に公開)...
echo     ログは server.log に保存されます
echo.
echo === 起動: %DATE% %TIME% === >> server.log
py -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=False)" >> server.log 2>&1

pause
