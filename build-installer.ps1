param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist\installer'),
    [string]$Compiler = (Join-Path $PSScriptRoot 'work\tools\inno\ISCC.exe'),
    [switch]$SkipClientBuild
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskStage = Join-Path $taskRoot 'work\installer-freeze'
if (-not $SkipClientBuild) {
    & (Join-Path $taskRoot 'build.ps1') -Target windows
    if (-not $?) { throw 'Windows client build failed.' }
}
$taskClient = Join-Path $taskRoot 'dist\windows'
$taskCrt = Get-ChildItem "${env:ProgramFiles(x86)}\Microsoft Visual Studio\*\BuildTools\VC\Redist\MSVC\*\x64\Microsoft.VC*.CRT" -Directory |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $taskCrt) { throw 'Visual C++ runtime files not found.' }
Copy-Item -Path (Join-Path $taskCrt.FullName '*.dll') -Destination $taskClient -Force
New-Item -ItemType Directory -Force -Path $taskStage,$OutputDirectory | Out-Null
$env:UV_CACHE_DIR = Join-Path $taskRoot 'server\.uv-cache'
Push-Location (Join-Path $taskRoot 'server')
try {
    uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Dependency preparation failed.' }
    uv run pyinstaller --noconfirm --clean --onedir --windowed --name ShijuanStudio `
        --distpath (Join-Path $taskRoot 'dist\installer-app') --workpath (Join-Path $taskStage 'build') `
        --specpath $taskStage --icon (Join-Path $taskRoot 'app\windows\runner\resources\app_icon.ico') `
        --add-data "$taskClient;desktop" `
        --collect-all latex2mathml --collect-all docx --collect-all resvg_py `
        --collect-all uvicorn --hidden-import main desktop_launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Application bundle build failed.' }
} finally { Pop-Location }
if (-not (Test-Path -LiteralPath $Compiler)) { throw 'Set -Compiler to the Inno Setup ISCC.exe path.' }
& $Compiler ('/DPayloadDir=' + (Join-Path $taskRoot 'dist\installer-app\ShijuanStudio')) `
    ('/DOutputDir=' + [IO.Path]::GetFullPath($OutputDirectory)) (Join-Path $taskRoot 'installer\Studio.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
Get-ChildItem -LiteralPath $OutputDirectory -Filter '*Setup*.exe' | Select-Object FullName,Length
