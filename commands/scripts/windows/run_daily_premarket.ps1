# WSL 版 — 每日盘前信号自动运行
# 用法: powershell -ExecutionPolicy Bypass -File run_daily_premarket.ps1

$ErrorActionPreference = "Stop"

$LogDir = "D:\HermesReports\daily_premarket_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Date = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "daily_premarket_$Date.log"

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Running Hermes daily premarket..." | Tee-Object -FilePath $LogFile

wsl -d Ubuntu -- bash -lc "cd ~/.hermes/research-assistant/commands && hermes factor:daily-premarket --capital 50000 --no-notify" *>&1 | Tee-Object -Append -FilePath $LogFile

if ($LASTEXITCODE -ne 0) {
    Write-Error "[$(Get-Date -Format 'HH:mm:ss')] FAILED. Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Completed. Log: $LogFile"
exit 0
