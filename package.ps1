param(
    [Parameter(Mandatory = $true)][string]$BuildRoot,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $taskOutput | Out-Null
$taskStage = Join-Path $PSScriptRoot ('work\package-' + [Guid]::NewGuid().ToString('N'))
$taskPackage = Join-Path $taskStage 'ShijuanStudio'
New-Item -ItemType Directory -Force -Path (Join-Path $taskPackage 'server') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $taskPackage 'windows') | Out-Null
Copy-Item -Path (Join-Path $BuildRoot 'build\windows\x64\runner\Release\*') -Destination (Join-Path $taskPackage 'windows') -Recurse
foreach ($taskFile in @('README.md','launch.cmd','launch.ps1','configure.cmd','start-server.cmd','start-server.ps1','stop-server.cmd','stop-server.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $taskFile) -Destination $taskPackage
}
Get-ChildItem -LiteralPath $taskOutput -Filter '*.txt' -File | Copy-Item -Destination $taskPackage
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'server') -File |
    Where-Object { $_.Extension -eq '.py' -or $_.Name -in @('pyproject.toml','uv.lock','.env.example') } |
    Copy-Item -Destination (Join-Path $taskPackage 'server')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'server\tests') -Destination (Join-Path $taskPackage 'server\tests') -Recurse
Get-ChildItem -LiteralPath (Join-Path $taskPackage 'server\tests') -Directory -Filter '__pycache__' |
    ForEach-Object {
        # Only the freshly created packaging workspace is eligible for cleanup.
        $taskResolved = [IO.Path]::GetFullPath($_.FullName)
        if (-not $taskResolved.StartsWith([IO.Path]::GetFullPath($taskStage) + '\')) { throw 'Unsafe staging path.' }
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
Compress-Archive -Path $taskPackage -DestinationPath (Join-Path $taskOutput 'ShijuanStudio-Windows-0.1.0.zip') -Force
$taskApk = Join-Path $BuildRoot 'build\app\outputs\flutter-apk\app-arm64-v8a-release.apk'
Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskOutput 'ShijuanStudio-Android-arm64-0.1.0.apk') -Force
$taskSource = Join-Path $taskStage 'ShijuanStudio-Source'
$taskSamples = [string]([char]0x6837) + [char]0x4f8b
robocopy $PSScriptRoot $taskSource /E /XD .venv .uv-cache __pycache__ .pytest_cache build .dart_tool .gradle .kotlin ephemeral dist work $taskSamples .git data /XF .env *.log /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw 'Source packaging failed.' }
Compress-Archive -Path $taskSource -DestinationPath (Join-Path $taskOutput 'ShijuanStudio-Source-0.1.0.zip') -Force
$taskDistWindows = Join-Path $PSScriptRoot 'dist\windows'
New-Item -ItemType Directory -Force -Path $taskDistWindows | Out-Null
Copy-Item -Path (Join-Path $taskPackage 'windows\*') -Destination $taskDistWindows -Recurse -Force
$taskDistAndroid = Join-Path $PSScriptRoot 'dist\android'
New-Item -ItemType Directory -Force -Path $taskDistAndroid | Out-Null
Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskDistAndroid 'shijuan-preview.apk') -Force
Get-ChildItem -LiteralPath $taskOutput -File | Where-Object { $_.Extension -in @('.zip','.apk') } |
    Get-FileHash -Algorithm SHA256 | Select-Object Hash,Path
