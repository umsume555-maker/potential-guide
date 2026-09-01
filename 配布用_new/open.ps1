$nasPath = "\\Ls210d50d\経理財務共有箱\2.決算情報\配布用\server_url.txt"
$localPath = Join-Path $PSScriptRoot "server_url.txt"
$logPath = Join-Path $PSScriptRoot "open_debug.log"

$url = $null

"[START] $(Get-Date)" | Out-File $logPath -Encoding UTF8

if (Test-Path $nasPath) {
    $line = Get-Content $nasPath -First 1 -ErrorAction SilentlyContinue
    if ($line) { $url = $line.Trim() }
    "[NAS URL] $url" | Out-File $logPath -Append -Encoding UTF8
} else {
    "[NAS] not found, using local" | Out-File $logPath -Append -Encoding UTF8
}

if (-not $url) {
    $line = Get-Content $localPath -First 1 -ErrorAction SilentlyContinue
    if ($line) { $url = $line.Trim() }
    "[LOCAL URL] $url" | Out-File $logPath -Append -Encoding UTF8
}

"[FINAL URL] $url" | Out-File $logPath -Append -Encoding UTF8

if (-not $url) {
    "[ERROR] URL empty" | Out-File $logPath -Append -Encoding UTF8
    Write-Host "URLが見つかりません。管理者にサーバーの起動を依頼してください。"
    Read-Host "Enterキーで終了"
    exit 1
}

Write-Host "接続先: $url"
Start-Process $url
Start-Sleep -Seconds 2
