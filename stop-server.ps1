$ErrorActionPreference = 'Stop'
$taskPidFile = Join-Path $PSScriptRoot 'logs\server-launcher.pid'
if (-not (Test-Path -LiteralPath $taskPidFile)) {
    Write-Host 'No background launcher found. If start-server.cmd is open, close that window.'
    exit 0
}
$taskPidText = (Get-Content -LiteralPath $taskPidFile -Raw).Trim()
if ($taskPidText -notmatch '^\d+$') { throw 'Invalid launcher record.' }
$taskServerPid = [int]$taskPidText
$taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskServerPid"
if (-not $taskProcess) { Write-Host 'The service launcher has already stopped.'; exit 0 }
$taskExpectedScript = Join-Path $PSScriptRoot 'start-server.ps1'
if ($taskProcess.Name -ne 'powershell.exe' -or -not $taskProcess.CommandLine.Contains($taskExpectedScript)) {
    throw 'The recorded process is not this app service. It was not stopped.'
}
& taskkill.exe /PID $taskServerPid /T /F
if ($LASTEXITCODE -ne 0) { throw 'Could not stop service launcher.' }
