$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskServer = Join-Path $taskRoot 'server'
# Development checkout: compile changed Flutter sources and run the current Python service.
if (Test-Path -LiteralPath (Join-Path $taskRoot 'app\pubspec.yaml')) {
    $taskClient = Join-Path $taskRoot 'dist\windows\shijuan_studio.exe'
    $taskSources = @(Get-ChildItem -LiteralPath (Join-Path $taskRoot 'app\lib'), (Join-Path $taskRoot 'app\windows') -Recurse -File |
        Where-Object { $_.FullName -notmatch '[\\/]ephemeral[\\/]' })
    $taskSources += Get-Item -LiteralPath (Join-Path $taskRoot 'app\pubspec.yaml'), (Join-Path $taskRoot 'app\pubspec.lock')
    $taskNeedsBuild = -not (Test-Path -LiteralPath $taskClient)
    if (-not $taskNeedsBuild) {
        $taskBuiltAt = (Get-Item -LiteralPath $taskClient).LastWriteTimeUtc
        $taskBuildStamp = Join-Path $taskRoot 'dist\windows\.source-built-at'
        if (Test-Path -LiteralPath $taskBuildStamp) {
            $taskBuiltAt = [DateTime]::Parse((Get-Content -LiteralPath $taskBuildStamp -Raw).Trim()).ToUniversalTime()
        }
        $taskNeedsBuild = [bool]($taskSources | Where-Object { $_.LastWriteTimeUtc -gt $taskBuiltAt } | Select-Object -First 1)
    }
    if ($taskNeedsBuild) {
        if (Get-Process -Name shijuan_studio -ErrorAction SilentlyContinue) {
            throw 'Close the existing app, then launch again to update the local client.'
        }
        & (Join-Path $taskRoot 'build.ps1') -Target windows
        if (-not $?) { throw 'Local client build failed.' }
    }
    $taskLog = Join-Path $taskRoot 'logs'
    New-Item -ItemType Directory -Path $taskLog -Force | Out-Null
    $env:UV_CACHE_DIR = Join-Path $taskServer '.uv-cache'
    $env:PYTHONUTF8 = '1'
    Start-Process -FilePath (Get-Command uv -ErrorAction Stop).Source -WindowStyle Hidden `
        -WorkingDirectory $taskServer -ArgumentList @('run', '--frozen', 'python', 'desktop_launcher.py') `
        -RedirectStandardOutput (Join-Path $taskLog 'desktop.log') `
        -RedirectStandardError (Join-Path $taskLog 'desktop-error.log')
    return
}
$taskExe = Join-Path $taskRoot 'windows\shijuan_studio.exe'
if (-not (Test-Path -LiteralPath $taskExe)) {
    $taskExe = Join-Path $taskRoot 'dist\windows\shijuan_studio.exe'
}
if (-not (Test-Path -LiteralPath $taskExe)) { throw 'Windows build not found. Extract the complete preview package first.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskServer '.env'))) {
    Copy-Item -LiteralPath (Join-Path $taskServer '.env.example') -Destination (Join-Path $taskServer '.env')
}
$taskHeaders = @{}
foreach ($taskLine in Get-Content -LiteralPath (Join-Path $taskServer '.env')) {
    if ($taskLine -match '^SERVICE_TOKEN=(.*)$' -and $Matches[1].Trim()) {
        $taskHeaders['Authorization'] = 'Bearer ' + $Matches[1].Trim().Trim('"').Trim("'")
    }
}
try {
    $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -Headers $taskHeaders -TimeoutSec 2
} catch {
    $taskLog = Join-Path $taskRoot 'logs'
    New-Item -ItemType Directory -Path $taskLog -Force | Out-Null
    $taskScript = Join-Path $taskRoot 'start-server.ps1'
    $taskProcess = Start-Process powershell -WindowStyle Hidden -PassThru `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $taskScript + '"')) `
        -RedirectStandardOutput (Join-Path $taskLog 'server.log') `
        -RedirectStandardError (Join-Path $taskLog 'server-error.log')
    Set-Content -LiteralPath (Join-Path $taskLog 'server-launcher.pid') -Value $taskProcess.Id
    for ($taskAttempt = 0; $taskAttempt -lt 60; $taskAttempt++) {
        Start-Sleep -Seconds 2
        try {
            $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -Headers $taskHeaders -TimeoutSec 1
            break
        } catch {
            if ($taskProcess.HasExited) { throw 'Service failed to start. See logs/server-error.log.' }
        }
    }
    if (-not $taskHealth) { throw 'Service startup timed out. See logs/server-error.log.' }
}
Start-Process -FilePath $taskExe
