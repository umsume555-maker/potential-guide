@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ============================================================
REM unzip_invoices.bat
REM ZIP一括展開スクリプト（請求書OCR用）
REM ============================================================

REM --- 設定 ---
set "SCRIPT_DIR=%~dp0"
set "ZIP_IN=%SCRIPT_DIR%ZIP_FILE_IN"
set "ZIP_OUT=%SCRIPT_DIR%ZIP_FILE_OUT"
set "LOG_DIR=%SCRIPT_DIR%logs"
set "FAILED_DIR=%ZIP_IN%\_FAILED"

REM --- 日付時刻取得 ---
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set "TODAY=%%a%%b%%c"
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "NOW=%%a%%b"
set "LOG_FILE=%LOG_DIR%\unzip_%TODAY%.log"

REM --- ディレクトリ作成 ---
if not exist "%ZIP_IN%" mkdir "%ZIP_IN%"
if not exist "%ZIP_OUT%" mkdir "%ZIP_OUT%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM --- ログ開始 ---
echo ============================================================ >> "%LOG_FILE%"
echo [%date% %time%] ZIP展開処理開始 >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

REM --- 7-Zip検索 ---
set "SEVEN_ZIP="

REM 1. ローカルの7zフォルダ
if exist "%SCRIPT_DIR%7z\7z.exe" (
    set "SEVEN_ZIP=%SCRIPT_DIR%7z\7z.exe"
    echo [INFO] 7-Zip found: %SCRIPT_DIR%7z\7z.exe >> "%LOG_FILE%"
    goto :found_7z
)

REM 2. PATH上の7z.exe
where 7z.exe >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "delims=" %%i in ('where 7z.exe') do set "SEVEN_ZIP=%%i"
    echo [INFO] 7-Zip found in PATH: !SEVEN_ZIP! >> "%LOG_FILE%"
    goto :found_7z
)

REM 3. 標準インストール場所
if exist "C:\Program Files\7-Zip\7z.exe" (
    set "SEVEN_ZIP=C:\Program Files\7-Zip\7z.exe"
    echo [INFO] 7-Zip found: C:\Program Files\7-Zip\7z.exe >> "%LOG_FILE%"
    goto :found_7z
)

REM 7-Zip が見つからない
echo [ERROR] 7-Zip が見つかりません >> "%LOG_FILE%"
echo [ERROR] 以下のいずれかを実行してください: >> "%LOG_FILE%"
echo         1. %SCRIPT_DIR%7z\ に 7z.exe と 7z.dll を配置 >> "%LOG_FILE%"
echo         2. 7-Zip をインストールして PATH を通す >> "%LOG_FILE%"
echo.
echo エラー: 7-Zip が見つかりません
echo %SCRIPT_DIR%7z\ に 7z.exe と 7z.dll を配置してください
pause
exit /b 1

:found_7z
echo [INFO] 使用する7-Zip: "%SEVEN_ZIP%" >> "%LOG_FILE%"

REM --- カウンタ初期化 ---
set /a TOTAL_COUNT=0
set /a SUCCESS_COUNT=0
set /a FAIL_COUNT=0

REM --- ZIP処理 ---
echo. >> "%LOG_FILE%"
echo --- ZIP処理開始 --- >> "%LOG_FILE%"

for %%f in ("%ZIP_IN%\*.zip") do (
    set /a TOTAL_COUNT+=1
    set "ZIP_NAME=%%~nf"
    set "ZIP_PATH=%%f"
    
    echo. >> "%LOG_FILE%"
    echo [!TOTAL_COUNT!] 処理中: %%~nxf >> "%LOG_FILE%"
    
    REM 展開先フォルダ決定
    set "OUT_DIR=%ZIP_OUT%\!ZIP_NAME!"
    
    REM 既存フォルダがあってもそのまま使用（上書き）
    if exist "!OUT_DIR!" (
        echo     既存フォルダあり → 上書きします >> "%LOG_FILE%"
    )
    
    REM 展開実行
    mkdir "!OUT_DIR!" 2>nul
    "%SEVEN_ZIP%" x "%%f" -o"!OUT_DIR!" -aoa -y > nul 2>&1
    set "EXIT_CODE=!ERRORLEVEL!"
    
    if !EXIT_CODE! EQU 0 (
        echo     [OK] 展開成功 → !OUT_DIR! >> "%LOG_FILE%"
        set /a SUCCESS_COUNT+=1
        
        REM 成功したZIPを削除
        del "%%f" 2>nul
        if exist "%%f" (
            echo     [WARN] ZIP削除失敗 >> "%LOG_FILE%"
        ) else (
            echo     [OK] ZIP削除完了 >> "%LOG_FILE%"
        )
    ) else (
        echo     [FAIL] 展開失敗 (Exit Code: !EXIT_CODE!) >> "%LOG_FILE%"
        set /a FAIL_COUNT+=1
        
        REM 失敗したZIPを_FAILEDに移動
        if not exist "%FAILED_DIR%" mkdir "%FAILED_DIR%"
        move "%%f" "%FAILED_DIR%\" >nul 2>&1
        echo     [INFO] %FAILED_DIR%\%%~nxf に移動 >> "%LOG_FILE%"
        
        REM 空の展開先を削除
        rmdir "!OUT_DIR!" 2>nul
    )
)

REM --- 集計 ---
echo. >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo [%date% %time%] ZIP展開処理完了 >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo 対象件数: %TOTAL_COUNT% >> "%LOG_FILE%"
echo 成功: %SUCCESS_COUNT% >> "%LOG_FILE%"
echo 失敗: %FAIL_COUNT% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

REM --- 画面出力 ---
echo.
echo ========================================
echo ZIP展開処理完了
echo ========================================
echo 対象件数: %TOTAL_COUNT%
echo 成功: %SUCCESS_COUNT%
echo 失敗: %FAIL_COUNT%
echo.
echo ログ: %LOG_FILE%
echo.

if %TOTAL_COUNT% EQU 0 (
    echo ZIP_FILE_IN フォルダにZIPファイルがありません
    echo %ZIP_IN%
)

pause
endlocal
