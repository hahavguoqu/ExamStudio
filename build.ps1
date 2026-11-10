param([ValidateSet('windows', 'android', 'all')][string]$Target = 'all')
$ErrorActionPreference = 'Stop'
$taskBuildStarted = [DateTime]::UtcNow
# Flutter native tools on Windows can corrupt non-ASCII build paths.
# Keep source in the user-requested directory; build from an ASCII workspace.
$taskBuild = Join-Path ([System.IO.Path]::GetTempPath()) 'shijuan-studio-build'
New-Item -ItemType Directory -Force -Path $taskBuild | Out-Null
robocopy (Join-Path $PSScriptRoot 'app') $taskBuild /E /XD build .dart_tool .gradle .kotlin ephemeral /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw 'Copying build sources failed.' }
Push-Location -LiteralPath $taskBuild
try {
    flutter pub get
    if ($LASTEXITCODE -ne 0) { throw 'Flutter dependency resolution failed.' }
    if ($Target -in @('windows', 'all')) {
        flutter build windows --release
        if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
        $taskWindows = Join-Path $PSScriptRoot 'dist\windows'
        New-Item -ItemType Directory -Force -Path $taskWindows | Out-Null
        Copy-Item -Path (Join-Path $taskBuild 'build\windows\x64\runner\Release\*') -Destination $taskWindows -Recurse -Force
        Set-Content -LiteralPath (Join-Path $taskWindows '.source-built-at') -Value $taskBuildStarted.ToString('o')
    }
    if ($Target -in @('android', 'all')) {
        flutter build apk --release --target-platform android-arm64 --split-per-abi
        if ($LASTEXITCODE -ne 0) { throw 'Android build failed.' }
        $taskAndroid = Join-Path $PSScriptRoot 'dist\android'
        New-Item -ItemType Directory -Force -Path $taskAndroid | Out-Null
        Copy-Item -LiteralPath (Join-Path $taskBuild 'build\app\outputs\flutter-apk\app-arm64-v8a-release.apk') -Destination (Join-Path $taskAndroid 'shijuan-preview.apk') -Force
    }
} finally { Pop-Location }
