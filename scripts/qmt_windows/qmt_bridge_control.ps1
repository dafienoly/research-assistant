param(
    [ValidateSet("setup", "install-deps", "use-big-qmt", "diagnose", "start", "stop", "restart", "status")]
    [string]$Action = "status",
    [string]$EnvFile = "",
    [string]$PythonPath = "",
    [string]$UserdataPath = "",
    [string]$AccountId = "",
    [string]$AccountType = "STOCK",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$EnableLiveTrading
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgeScript = (Resolve-Path (Join-Path $ScriptDir "..\qmt_bridge.py")).ProviderPath
$RuntimeDir = Join-Path $ScriptDir "runtime"
$PidFile = Join-Path $RuntimeDir "qmt_bridge.pid"
$OutLog = Join-Path $RuntimeDir "qmt_bridge.out.log"
$ErrLog = Join-Path $RuntimeDir "qmt_bridge.err.log"
$DefaultEnvFile = Join-Path $ScriptDir "qmt_bridge.env"
$ExampleEnvFile = Join-Path $ScriptDir "qmt_bridge.env.example"
if (-not $EnvFile) { $EnvFile = $DefaultEnvFile }

function Ensure-RuntimeDir {
    if (-not (Test-Path $RuntimeDir)) {
        New-Item -ItemType Directory -Path $RuntimeDir | Out-Null
    }
}

function Write-Info([string]$Message) {
    Write-Host "[qmt-bridge] $Message"
}

function Resolve-Python {
    if ($PythonPath) { return $PythonPath }
    $compatible = Resolve-CompatiblePython
    if ($compatible) { return $compatible }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "Python not found. Pass -PythonPath or add python.exe to PATH."
}

function Get-PythonVersion([string]$Path) {
    if (-not $Path) { return $null }
    if ($Path.EndsWith("py.exe")) { return $null }
    if (-not (Test-Path $Path)) { return $null }
    try {
        $out = & $Path -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        return [version]$out.Trim()
    } catch {
        return $null
    }
}

function Test-XtquantPythonCompatible([string]$Path) {
    $ver = Get-PythonVersion $Path
    if (-not $ver) { return $false }
    return ($ver -ge [version]"3.6" -and $ver -lt [version]"3.14")
}

function Resolve-CompatiblePython {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($PythonPath) { $candidates.Add($PythonPath) }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($tag in @("3.13", "3.12", "3.11", "3.10", "3.9")) {
            try {
                $path = (& py "-$tag" -c "import sys; print(sys.executable)" 2>$null)
                if ($LASTEXITCODE -eq 0 -and $path) { $candidates.Add($path.Trim()) }
            } catch {}
        }
    }

    foreach ($path in @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )) {
        $candidates.Add($path)
    }

    $seen = @{}
    foreach ($path in $candidates) {
        if (-not $path -or $seen.ContainsKey($path)) { continue }
        $seen[$path] = $true
        if (Test-XtquantPythonCompatible $path) { return $path }
    }
    return ""
}

function Load-EnvFile([string]$Path) {
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $map[$key] = $value
    }
    return $map
}

function Apply-Env([hashtable]$Map) {
    foreach ($key in $Map.Keys) {
        [Environment]::SetEnvironmentVariable($key, [string]$Map[$key], "Process")
    }
}

function Set-EnvValueInFile([string]$Path, [string]$Key, [string]$Value) {
    $lines = @()
    $found = $false
    if (Test-Path $Path) {
        foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
            if ($line -match "^\s*$([regex]::Escape($Key))=") {
                $lines += "$Key=$Value"
                $found = $true
            } else {
                $lines += $line
            }
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function Write-EnvFile {
    param(
        [string]$Path,
        [string]$ResolvedPython
    )
    Ensure-RuntimeDir
    $auditPath = Join-Path $RuntimeDir "qmt_bridge_audit.jsonl"
    $live = if ($EnableLiveTrading) { "1" } else { "0" }
    $content = @"
# QMT Bridge Windows environment file.
# Generated by qmt_bridge_control.ps1 setup.

QMT_BRIDGE_HOST=$HostAddress
QMT_BRIDGE_PORT=$Port

QMT_USERDATA_PATH=$UserdataPath
QMT_ACCOUNT_ID=$AccountId
QMT_ACCOUNT_TYPE=$AccountType
QMT_SESSION_ID=100
QMT_CLIENT_MODE=research
QMT_XTDATA_PORT=

QMT_LIVE_TRADING_ENABLED=$live
QMT_BRIDGE_AUDIT_PATH=$auditPath
QMT_PYTHON_PATH=$ResolvedPython
"@
    Set-Content -Path $Path -Value $content -Encoding UTF8
}

function Get-BridgeProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $pidText = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $pidText) { return $null }
    try {
        $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if (-not $proc) { return $null }
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction SilentlyContinue
        if ($cim -and $cim.CommandLine -and $cim.CommandLine.Contains("qmt_bridge.py")) {
            return $proc
        }
    } catch {
        return $null
    }
    return $null
}

function Get-BridgeUrl([hashtable]$EnvMap) {
    $hostValue = if ($EnvMap.ContainsKey("QMT_BRIDGE_HOST")) { $EnvMap["QMT_BRIDGE_HOST"] } else { $HostAddress }
    $portValue = if ($EnvMap.ContainsKey("QMT_BRIDGE_PORT")) { $EnvMap["QMT_BRIDGE_PORT"] } else { $Port }
    return "http://$hostValue`:$portValue"
}

function Invoke-Health([string]$BaseUrl) {
    try {
        return Invoke-RestMethod -Uri "$BaseUrl/health" -Method GET -TimeoutSec 3
    } catch {
        return $null
    }
}

function Wait-Health([string]$BaseUrl, [int]$Seconds = 12) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        $health = Invoke-Health $BaseUrl
        if ($health) { return $health }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Setup-Bridge {
    Ensure-RuntimeDir
    if (-not (Test-Path $ExampleEnvFile)) {
        throw "Missing example env file: $ExampleEnvFile"
    }
    $python = Resolve-Python
    if (-not $UserdataPath -or -not $AccountId) {
        if (Test-Path $EnvFile) {
            Write-Info "Keeping existing config: $EnvFile"
            return
        }
        Copy-Item -Path $ExampleEnvFile -Destination $EnvFile
        Add-Content -Path $EnvFile -Value "QMT_PYTHON_PATH=$python"
        Write-Info "Created template config: $EnvFile"
        Write-Info "Edit QMT_USERDATA_PATH and QMT_ACCOUNT_ID before querying account/trading endpoints."
        return
    }
    Write-EnvFile -Path $EnvFile -ResolvedPython $python
    Write-Info "Wrote config: $EnvFile"
    Write-Info "Live trading enabled: $(if ($EnableLiveTrading) { 'YES' } else { 'NO' })"
}

function Install-Dependencies {
    Ensure-RuntimeDir
    $envMap = Load-EnvFile $EnvFile
    $python = if ($envMap.ContainsKey("QMT_PYTHON_PATH") -and $envMap["QMT_PYTHON_PATH"]) { $envMap["QMT_PYTHON_PATH"] } else { Resolve-Python }
    if (-not (Test-XtquantPythonCompatible $python)) {
        $old = $python
        $python = Resolve-CompatiblePython
        if (-not $python) {
            throw "xtquant requires Python >=3.6 and <3.14. Current Python is incompatible: $old. Install Python 3.12 or 3.11, then rerun install_qmt_dependencies.cmd."
        }
        Write-Info "Configured Python is not xtquant-compatible: $old"
        Write-Info "Switching QMT_PYTHON_PATH to compatible Python: $python"
        Set-EnvValueInFile -Path $EnvFile -Key "QMT_PYTHON_PATH" -Value $python
    }
    Write-Info "Installing xtquant into: $python"
    & $python -m pip install xtquant -i https://pypi.org/simple
    if ($LASTEXITCODE -ne 0) {
        throw "pip install xtquant failed with exit code $LASTEXITCODE"
    }
    Write-Info "Dependency install complete."
}

function Use-BigQmt {
    if (-not (Test-Path $EnvFile)) {
        throw "Config not found: $EnvFile. Run setup_qmt_bridge.cmd first."
    }
    $envMap = Load-EnvFile $EnvFile
    $path = if ($envMap.ContainsKey("QMT_USERDATA_PATH")) { $envMap["QMT_USERDATA_PATH"] } else { "" }
    if (-not $path) {
        throw "QMT_USERDATA_PATH is empty. Set it to your QMT userdata directory."
    }
    $target = $path
    if ((Split-Path $path -Leaf) -eq "userdata_mini") {
        $sibling = Join-Path (Split-Path $path -Parent) "userdata"
        if (Test-Path $sibling) { $target = $sibling }
    }
    if ((Split-Path $target -Leaf) -ne "userdata") {
        Write-Info "Warning: big QMT / research mode normally uses a path ending in 'userdata'. Current: $target"
    }
    Set-EnvValueInFile -Path $EnvFile -Key "QMT_CLIENT_MODE" -Value "research"
    Set-EnvValueInFile -Path $EnvFile -Key "QMT_USERDATA_PATH" -Value $target
    Set-EnvValueInFile -Path $EnvFile -Key "QMT_XTDATA_PORT" -Value $(if ($envMap.ContainsKey("QMT_XTDATA_PORT")) { $envMap["QMT_XTDATA_PORT"] } else { "" })
    Write-Info "Configured big QMT / research mode."
    Write-Info "QMT_USERDATA_PATH=$target"
    Write-Info "If xtdata still cannot connect, set QMT_XTDATA_PORT to the data-service port shown in QMT."
}

function Diagnose-Bridge {
    $envMap = Load-EnvFile $EnvFile
    $python = if ($envMap.ContainsKey("QMT_PYTHON_PATH") -and $envMap["QMT_PYTHON_PATH"]) { $envMap["QMT_PYTHON_PATH"] } else { Resolve-Python }
    Write-Info "Config: $EnvFile"
    Write-Info "Python: $python"
    $pyVer = Get-PythonVersion $python
    Write-Info "Python version: $pyVer"
    Write-Info "Python xtquant-compatible: $(Test-XtquantPythonCompatible $python)"
    if ($envMap.ContainsKey("QMT_USERDATA_PATH")) {
        $path = $envMap["QMT_USERDATA_PATH"]
        Write-Info "QMT_USERDATA_PATH exists: $(Test-Path $path)"
        Write-Info "QMT_USERDATA_PATH leaf: $(Split-Path $path -Leaf)"
    }
    if ($envMap.ContainsKey("QMT_CLIENT_MODE")) { Write-Info "QMT_CLIENT_MODE: $($envMap["QMT_CLIENT_MODE"])" }
    if ($envMap.ContainsKey("QMT_XTDATA_PORT")) { Write-Info "QMT_XTDATA_PORT: $($envMap["QMT_XTDATA_PORT"])" }

    Write-Host ""
    Write-Info "QMT/XT related processes:"
    Get-Process | Where-Object { $_.ProcessName -match 'qmt|xt|think|trader' } |
        Select-Object Id, ProcessName, Path | Sort-Object ProcessName | Format-Table -AutoSize

    Write-Host ""
    Write-Info "Listening ports near xtquant default 58610:"
    $ports = netstat -ano | Select-String ':5860|:5861|:5862'
    if ($ports) { $ports } else { Write-Info "No 586xx listener found." }

    Write-Host ""
    Write-Info "xtquant package check:"
    & $python -c "import xtquant; from xtquant import xtconn; print('xtquant ok', xtquant.__file__); print('scan_available_server_addr=', xtconn.scan_available_server_addr())"
    if ($LASTEXITCODE -ne 0) {
        Write-Info "xtquant import/scan failed."
    }

    Write-Host ""
    Write-Info "Interpretation:"
    Write-Info "For big QMT / research mode, QMT_USERDATA_PATH should end with 'userdata'."
    Write-Info "If scan_available_server_addr=[] and no 586xx listener exists, QMT data service is not exposed to xtquant."
    Write-Info "Open QMT's research/quant/Python/data-service setting if available, or use 极简模式/独立交易模式 if your broker build requires it."
}

function Start-Bridge {
    Ensure-RuntimeDir
    $running = Get-BridgeProcess
    if ($running) {
        Write-Info "Already running. PID $($running.Id)"
        return
    }
    if (-not (Test-Path $EnvFile)) {
        Write-Info "Config not found; creating template first."
        Setup-Bridge
    }
    $envMap = Load-EnvFile $EnvFile
    Apply-Env $envMap
    $python = if ($envMap.ContainsKey("QMT_PYTHON_PATH") -and $envMap["QMT_PYTHON_PATH"]) { $envMap["QMT_PYTHON_PATH"] } else { Resolve-Python }
    if (-not (Test-XtquantPythonCompatible $python)) {
        throw "QMT_PYTHON_PATH is not xtquant-compatible: $python. Run install_qmt_dependencies.cmd to auto-select Python 3.12/3.11."
    }
    $hostValue = if ($envMap.ContainsKey("QMT_BRIDGE_HOST")) { $envMap["QMT_BRIDGE_HOST"] } else { $HostAddress }
    $portValue = if ($envMap.ContainsKey("QMT_BRIDGE_PORT")) { $envMap["QMT_BRIDGE_PORT"] } else { $Port }
    $args = @("`"$BridgeScript`"", "--host", $hostValue, "--port", $portValue)
    $proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $ScriptDir -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru -WindowStyle Hidden
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
    $url = Get-BridgeUrl $envMap
    $health = Wait-Health $url 12
    if ($health) {
        Write-Info "Started PID $($proc.Id): $url"
        Write-Info "Health: $($health.status)"
        Write-Host ($health | ConvertTo-Json -Depth 5)
    } else {
        Write-Info "Started PID $($proc.Id), but health check failed. Check logs:"
        Write-Info "stdout: $OutLog"
        Write-Info "stderr: $ErrLog"
    }
}

function Stop-Bridge {
    $proc = Get-BridgeProcess
    if (-not $proc) {
        if (Test-Path $PidFile) { Remove-Item -Path $PidFile -Force }
        Write-Info "Not running."
        return
    }
    Stop-Process -Id $proc.Id -Force
    if (Test-Path $PidFile) { Remove-Item -Path $PidFile -Force }
    Write-Info "Stopped PID $($proc.Id)."
}

function Show-Status {
    $envMap = Load-EnvFile $EnvFile
    $proc = Get-BridgeProcess
    $url = Get-BridgeUrl $envMap
    if ($proc) {
        Write-Info "Running PID $($proc.Id): $url"
        $health = Invoke-Health $url
        if ($health) {
            Write-Host ($health | ConvertTo-Json -Depth 5)
        } else {
            Write-Info "Health check failed."
        }
    } else {
        Write-Info "Stopped."
    }
    Write-Info "Config: $EnvFile"
    Write-Info "Logs: $OutLog ; $ErrLog"
}

switch ($Action) {
    "setup" { Setup-Bridge }
    "install-deps" { Install-Dependencies }
    "use-big-qmt" { Use-BigQmt }
    "diagnose" { Diagnose-Bridge }
    "start" { Start-Bridge }
    "stop" { Stop-Bridge }
    "restart" { Stop-Bridge; Start-Sleep -Seconds 1; Start-Bridge }
    "status" { Show-Status }
}
