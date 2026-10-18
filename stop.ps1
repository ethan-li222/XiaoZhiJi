param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'data\logs\server.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { throw 'No managed PID file. Stop manually started servers in their terminal.' }
$serverPid = [int](Get-Content -LiteralPath $pidFile)
$managed = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
if (-not $managed) { Write-Host 'Managed server is already stopped.'; exit 0 }
if ($managed.CommandLine -notlike '*uvicorn research_agent.api:app*' -or $managed.CommandLine -notlike "*--port $Port*") {
    throw 'PID does not match the managed XiaoZhiJi server. No process was stopped.'
}
Stop-Process -Id $serverPid -ErrorAction Stop
Wait-Process -Id $serverPid -Timeout 10 -ErrorAction SilentlyContinue
Write-Host 'XiaoZhiJi stopped. Unfinished tasks can be resumed after restart.'
