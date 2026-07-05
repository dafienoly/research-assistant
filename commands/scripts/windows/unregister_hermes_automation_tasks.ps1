# Unregister Hermes automation tasks

$TaskName = "Hermes Auto Loop"

schtasks /Delete /TN $TaskName /F

Write-Host "✅ Unregistered: $TaskName"
