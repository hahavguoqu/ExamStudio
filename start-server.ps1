$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot 'server')
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot 'server\.uv-cache'
$env:PYTHONUTF8 = '1'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install uv, then run this script again.'
}
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
uv run uvicorn main:app --host 0.0.0.0 --port 8765
