# ExamStudio

[中文](README.md) | **English**

A mathematics paper conversion and assisted authoring workspace for teachers. A Flutter client runs on Windows and Android; a Python service handles documents, DeepSeek API calls, figures, and Word exports.

## Features

- **Convert papers to Word:** import PNG, JPG, WebP, PDF, and DOCX; recognize questions, tables, and formulas. Equations are exported as editable Word OMML, with figures available as images and SVG resources.
- **Author from reference questions:** analyze knowledge points and solutions, then produce candidate questions, independent solutions, and review feedback.
- **Author from a brief:** specify grade, question type, subject matter, and context; confirm an editable brief before generation. Reference search is optional.
- **Teacher-directed revision:** discuss questions, create revised versions, inspect figure drafts, and select original or redrawn figures while retaining earlier versions.
- **Persistent tasks and exports:** keep saved tasks, candidates, and conversations; resume from saved intermediate results and export student papers, answer explanations, and figure resources.

Teachers should check mathematical correctness, transcription, and generated figures. In the single-question authoring flow, review feedback is advisory and saved candidates can be previewed and exported. Review gates in other workflows follow the application's prompts.

## Requirements

| Component | Requirement |
| --- | --- |
| Python service | Python 3.11+, managed with [uv](https://docs.astral.sh/uv/) |
| Flutter client | Stable Flutter with Dart 3.11.1, or a compatible version allowed by `app/pubspec.yaml` |
| Windows development | Windows x64, Visual Studio Desktop development with C++, and Windows SDK |
| Android development | Android SDK, JDK 17, accepted SDK licenses; Android 7.0 minimum |
| Model API | A valid DeepSeek API key with access to the configured models, vision, and optional search endpoints |
| Optional | LibreOffice for legacy `.doc` files and workflows requiring original-layout conversion |

This repository contains source code and build scripts. Installers, APKs, virtual environments, personal exam papers, and runtime data are excluded.

## Run from source on Windows

Install Git, uv, Flutter, and the Windows build tools, then run in PowerShell:

```powershell
git clone https://github.com/hahavguoqu/ExamStudio.git
Set-Location ExamStudio
$env:UV_CACHE_DIR = "$PWD\server\.uv-cache"
uv sync --project server --frozen
.\launch.cmd
```

The launcher rebuilds the Windows client when necessary and starts a private local service with the application window. The first build can take some time. Enter your DeepSeek API key in the connection/settings screen. Desktop mode manages its own loopback address and random service token. Closing the window shuts down that desktop service. Restart the application after source changes.

Desktop credentials are encrypted with Windows DPAPI under `%LOCALAPPDATA%\ShijuanStudio`. Source mode stores tasks in `server/data` by default, or the `DATA_DIR` configured in `server/.env`. Packaged desktop builds use `%LOCALAPPDATA%\ShijuanStudio\tasks`.

## Android and LAN service

The Android client connects to the Python service on a computer or server. Model processing happens on that service.

1. Create and edit a local configuration file:

   ```powershell
   Copy-Item server\.env.example server\.env
   notepad server\.env
   ```

2. Set `DEEPSEEK_API_KEY`. Remote access also requires a random `SERVICE_TOKEN` of at least 24 characters.
3. Run `.\start-server.cmd` from the repository root. The default port is `8765`.
4. Enter the host's LAN address, such as `http://192.168.1.10:8765`, and the same token in the Android client.

Restart the service after changing configuration. Avoid running the desktop service and a standalone service against the same task directory. The shared-token design is intended for an individual or a trusted group; it does not provide separate accounts or per-user data isolation. Internet deployments need additional HTTPS and access controls.

### Configuration

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | Server-side DeepSeek credential |
| `DEEPSEEK_BASE_URL` | API base URL; defaults to `https://api.deepseek.com` |
| `VISION_MODEL` / `REASONING_MODEL` | Vision and reasoning models; the template uses `deepseek-flash` |
| `SERVICE_TOKEN` | Shared service token; without a token, only local access is allowed |
| `DATA_DIR` | Task, upload, and export storage directory |
| `SOFFICE_PATH` | Optional LibreOffice executable path |
| `MODEL_CONCURRENCY` | Concurrent model calls; the template uses `3` |

See [`server/.env.example`](server/.env.example). Saving a key does not validate account permissions, available models, or credit.

## Build and verify

Backend tests use isolated data and model substitutes; a real API key is not required:

```powershell
Set-Location server
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --frozen
uv run --frozen pytest -q
```

Client checks:

```powershell
Set-Location app
flutter pub get
flutter analyze
flutter test
```

Build from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Target windows
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Target android
```

The script uses an ASCII temporary build path to avoid Windows native-tool issues with non-ASCII paths. Outputs go to `dist/windows` and `dist/android`. Android currently uses a development signing key; configure production signing before distribution.

- `build-single-exe.ps1` creates `dist/standalone/ShijuanStudio.exe` with PyInstaller.
- `build-installer.ps1 -Compiler <path-to-ISCC.exe>` builds a Windows installer with a local Inno Setup installation.
- `package.ps1` packages an existing build; see the script for its parameters.

## Repository layout

```text
app/                  Flutter UI, platform projects, and client tests
server/
  main.py             API, authentication, tasks, and exports
  pipeline.py         Conversion and reference-based authoring
  brief_generation.py Brief confirmation and question authoring
  model.py            DeepSeek adapter, validation, and retries
  documents.py        Documents, equations, images, and DOCX
  drafts.py           Candidates, revisions, and export snapshots
  reference_search.py Optional reference search
  desktop_launcher.py Private desktop service entry point
  tests/              Backend tests
installer/            Inno Setup definitions
build*.ps1            Build scripts
```

## Data handling and limitations

- Recognition, authoring, discussions, and optional search call external APIs. Relevant material may be sent to the configured provider; confirm that your documents are suitable for that service. API usage may incur charges.
- Upload limits: 30 files, 40 pages, 30 MB per file, and 100 MB in total.
- Scanned layouts are not reproduced pixel for pixel. Complex geometry, handwritten annotations, tables, and cross-page questions need manual review. Word equations are editable; figures remain images, with SVG source included as resources.
- Saved progress survives interruptions. Tasks stop when the service stops, and resuming can reuse only stages that were actually saved.
- Search references do not establish originality or guarantee correctness. Sources without retrieved full text are identified accordingly.
- `.gitignore` excludes credentials, local settings, task data, original paper samples, logs, caches, and build artifacts. Always inspect staged files before publishing; templates should contain only empty secrets and public defaults.
