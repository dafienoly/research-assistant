$ErrorActionPreference = "Stop"

$qmtRoot = Get-ChildItem "D:\" -Directory |
    Where-Object {
        (Test-Path (Join-Path $_.FullName "bin.x64\python.exe")) -and
        (Test-Path (Join-Path $_.FullName "userdata\users"))
    } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $qmtRoot) {
    throw "No QMT installation found on drive D"
}
$python = Join-Path $qmtRoot "bin.x64\python.exe"
$userdata = Join-Path $qmtRoot "userdata_mini"
$accountRoot = Join-Path $qmtRoot "userdata\users"
$account = Get-ChildItem $accountRoot -Directory |
    Where-Object { $_.Name -match '^\d{6,16}$' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $account) {
    throw "No numeric QMT account directory found under userdata\users"
}

$env:QMT_USERDATA_PATH = $userdata
$env:QMT_ACCOUNT_ID = $account.Name
$env:QMT_ACCOUNT_TYPE = "STOCK"
$env:QMT_BRIDGE_HOST = "0.0.0.0"
$env:QMT_BRIDGE_PORT = "8765"
$env:QMT_LIVE_TRADING_ENABLED = "0"

$existing = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'qmt_bridge.py' -and $_.ProcessId -ne $PID }
foreach ($process in $existing) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Process -FilePath $python -ArgumentList @(
    "C:\Users\ly\Desktop\qmt_bridge.py",
    "--host", "0.0.0.0",
    "--port", "8765"
) -WindowStyle Hidden
