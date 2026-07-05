# Register Hermes automation tasks via Windows schtasks
# 每 3 分钟运行 WSL 脚本

$TaskName = "Hermes Auto Loop"
$ScriptPath = "C:\Users\ly\wsl_scripts\run_hermes_agent_runner.bat"

# Create WSL bridge batch file
$BatchDir = [System.IO.Path]::GetDirectoryName($ScriptPath)
if (-not (Test-Path $BatchDir)) { New-Item -ItemType Directory -Force -Path $BatchDir }

@"
@echo off
wsl -d Ubuntu -- bash -lc "/home/ly/.hermes/research-assistant/commands/scripts/run_hermes_agent_runner.sh"
"@ | Out-File -FilePath $ScriptPath -Encoding ASCII

# Register schtasks
schtasks /Create /TN $TaskName /SC MINUTE /MO 3 /TR "cmd.exe /c `"$ScriptPath`"" /F

Write-Host "✅ Registered: $TaskName (every 3 min)"
