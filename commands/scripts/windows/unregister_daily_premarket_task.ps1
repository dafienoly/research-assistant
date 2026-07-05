# 取消 Hermes 每日盘前计划任务
# 用法: powershell -ExecutionPolicy Bypass -File unregister_daily_premarket_task.ps1

$TaskName = "Hermes Daily Premarket Signal"

Write-Host "Unregistering scheduled task: $TaskName"

schtasks /Delete /TN $TaskName /F

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Task '$TaskName' unregistered."
} else {
    Write-Error "❌ Failed to unregister task. Exit code: $LASTEXITCODE"
    exit $LASTEXITCODE
}
