param([int]$Port = 8765, [switch]$NoBrowser, [switch]$Restart)
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonPath = Join-Path $env:USERPROFILE '.conda\envs\agent\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
$address = "http://127.0.0.1:$Port"
$pidFile = Join-Path $projectDirectory 'data\logs\server.pid'
$existing = $null
try { $existing = Invoke-RestMethod "$address/info" -TimeoutSec 2 } catch {}
if ($Restart -and $existing.application -eq 'research-agent') {
    if (-not (Test-Path -LiteralPath $pidFile)) { throw 'No managed server PID found. Stop the existing server manually first.' }
    $serverPid = [int](Get-Content -LiteralPath $pidFile)
    $managed = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
    if (-not $managed -or $managed.CommandLine -notlike '*uvicorn research_agent.api:app*' -or $managed.CommandLine -notlike "*--port $Port*") {
        throw 'PID does not match the managed XiaoZhiJi server. No process was stopped.'
    }
    Stop-Process -Id $serverPid -ErrorAction Stop
    Wait-Process -Id $serverPid -Timeout 10 -ErrorAction SilentlyContinue
    $existing = $null
}
if ($existing.application -eq 'research-agent') {
    Write-Host "XiaoZhiJi is running: $address"
    if (-not $NoBrowser) { Start-Process $address }
    exit 0
}
$env:PYTHONPATH = Join-Path $projectDirectory 'src'
$env:PYTHONIOENCODING = 'utf-8'
$logDirectory = Join-Path $projectDirectory 'data\logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$errorLog = Join-Path $logDirectory "$stamp-error.log"
$server = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','research_agent.api:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory "$stamp-output.log") -RedirectStandardError $errorLog
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($server.HasExited) { throw "Server stopped. See $errorLog" }
    try {
        $status = Invoke-RestMethod "$address/info" -TimeoutSec 2
        if ($status.application -eq 'research-agent') {
            Set-Content -LiteralPath (Join-Path $logDirectory 'server.pid') -Value $server.Id
            Write-Host "XiaoZhiJi is ready: $address (PID $($server.Id))"
            if (-not $NoBrowser) { Start-Process $address }
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}
throw "Startup timed out. See $errorLog"
