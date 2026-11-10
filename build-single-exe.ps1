$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$stage = Join-Path $env:TEMP 'shijuan-single-exe'
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$appStage = Join-Path $stage 'app'
robocopy (Join-Path $root 'app') $appStage /E /XD build .dart_tool .gradle .kotlin ephemeral /NFL /NDL /NJH /NJS /NP | Out-Null
Push-Location $appStage
try {
    flutter pub get
    if ($LASTEXITCODE) { throw 'Flutter dependencies failed' }
    flutter build windows --release
    if ($LASTEXITCODE) { throw 'Windows build failed' }
} finally { Pop-Location }
$redistributable = Get-ChildItem "${env:ProgramFiles(x86)}\Microsoft Visual Studio\*\BuildTools\VC\Redist\MSVC\*\x64\Microsoft.VC*.CRT" -Directory |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $redistributable) { throw 'Visual C++ redistributable DLLs not found' }
Copy-Item "$($redistributable.FullName)\*.dll" "$appStage\build\windows\x64\runner\Release"
Push-Location (Join-Path $root 'server')
try {
    uv sync --frozen
    if ($LASTEXITCODE) { throw 'Python dependencies failed' }
    uv run pyinstaller --noconfirm --clean --onefile --windowed --name ShijuanStudio `
        --distpath (Join-Path $root 'dist\standalone') --workpath (Join-Path $stage 'freeze') `
        --specpath $stage --icon (Join-Path $root 'app\windows\runner\resources\app_icon.ico') `
        --add-data "$appStage\build\windows\x64\runner\Release;desktop" `
        --collect-all latex2mathml --collect-all docx --collect-all resvg_py `
        --collect-all uvicorn --hidden-import main desktop_launcher.py
    if ($LASTEXITCODE) { throw 'Single EXE build failed' }
} finally { Pop-Location }
