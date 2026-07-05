# 注册 Hermes 每日盘前计划任务
# 用法: powershell -ExecutionPolicy Bypass -File register_daily_premarket_task.ps1 [-Time "08:45"]

param([string]$Time = "08:45")

$TaskName = "Hermes Daily Premarket Signal"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ScriptDir "run_daily_premarket.ps1"

Write-Host "Registering scheduled task: $TaskName"
Write-Host "  Time: $Time"
Write-Host "  Script: $ScriptPath"

schtasks /Create /TN $TaskName /SC DAILY /ST $Time /TR "powershell.exe -ExecutionPolicy Bypass -File `"$ScriptPath`"" /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Task '$TaskName' registered successfully. Runs daily at $Time."
} else {
    Write-Error "❌ Failed to register task. Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}
