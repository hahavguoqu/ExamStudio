# ExamStudio · 试卷工作室

**中文** | [English](README.en.md)

面向数学教师的试卷转换与辅助命题工具。Flutter 提供 Windows / Android 客户端，Python 服务负责文档处理、DeepSeek API 调用、配图处理和 Word 导出。

## 主要功能

- **试卷转 Word**：导入 PNG、JPG、WebP、PDF、DOCX，识别题目、表格与公式。公式导出为可在 Word / WPS 中编辑的原生 OMML，配图提供图片和 SVG 资源。
- **参考题出题**：分析原题知识点和解法，生成候选题、独立解答和审核意见。
- **按要求出题**：填写年级、题型、考查内容及背景，先确认可编辑的命题要求，再生成题目；可选择联网检索参考资料。
- **教师参与修改**：讨论题目、按意见创建修改版本、查看配图草稿、选择原图或重绘图，并保留修改记录。
- **任务与导出**：保存任务、候选版本和对话；已保存的中间结果可供后续继续处理；导出学生卷、答案解析及配图资源。

数学正确性、识别结果和 AI 配图需要教师核对。单题命题流程的审核提供建议，已有候选可供预览和导出；不同工作流的审核门槛以界面提示为准。

## 运行环境

| 组件 | 要求 |
| --- | --- |
| Python 服务 | Python 3.11+，使用 [uv](https://docs.astral.sh/uv/) 管理环境 |
| Flutter 客户端 | Flutter 稳定版，包含 Dart 3.11.1 或满足 `app/pubspec.yaml` 的版本 |
| Windows 开发 | Windows x64，Visual Studio C++ 桌面开发工具与 Windows SDK |
| Android 开发 | Android SDK、JDK 17、已接受的 SDK 许可证；最低 Android 7.0 |
| 模型服务 | 有效的 DeepSeek API Key，以及所配置模型、视觉和可选搜索接口的访问权限 |
| 可选组件 | LibreOffice，用于旧版 `.doc` 和需要原版布局转换的工作流 |

本仓库提供源代码和构建脚本。安装程序、APK、虚拟环境、用户试卷和运行数据不包含在源码中。

## Windows：从源码启动

先安装 Git、uv、Flutter 和 Windows 构建工具，再在 PowerShell 中执行：

```powershell
git clone https://github.com/hahavguoqu/ExamStudio.git
Set-Location ExamStudio
$env:UV_CACHE_DIR = "$PWD\server\.uv-cache"
uv sync --project server --frozen
.\launch.cmd
```

`launch.cmd` 会检查客户端是否需要重新构建，然后启动本机私有后台和窗口。首次构建可能需要较长时间。在“连接与设置”中填写 DeepSeek API Key；桌面模式自动管理连接地址和随机服务口令。关闭窗口后，该桌面后台随之退出。源码变更后关闭并重新启动软件。

桌面 Key 使用 Windows DPAPI 加密保存在 `%LOCALAPPDATA%\ShijuanStudio`。源码模式默认把任务保存在 `server/data`，也可由 `server/.env` 中的 `DATA_DIR` 配置。打包后的桌面程序把任务保存在 `%LOCALAPPDATA%\ShijuanStudio\tasks`。

## Android / 局域网服务

Android 客户端连接运行在电脑或服务器上的 Python 服务，模型处理发生在服务端。

1. 复制配置模板并编辑本地文件：

   ```powershell
   Copy-Item server\.env.example server\.env
   notepad server\.env
   ```

2. 填写 `DEEPSEEK_API_KEY`。远程连接还需设置至少 24 个字符的随机 `SERVICE_TOKEN`。
3. 在项目根目录运行 `.\start-server.cmd`；默认端口为 `8765`。
4. 在 Android 客户端填写服务电脑的局域网地址，例如 `http://192.168.1.10:8765`，以及相同的服务口令。

修改配置后重启服务。避免桌面私有后台和独立服务同时写入同一个任务目录。当前共享口令模式面向单人或可信小组，没有多人账号及用户间数据隔离；公网部署应另外配置 HTTPS 和访问控制。

### 服务配置

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 服务端 DeepSeek 密钥 |
| `DEEPSEEK_BASE_URL` | API 地址，默认 `https://api.deepseek.com` |
| `VISION_MODEL` / `REASONING_MODEL` | 视觉和推理模型；模板默认 `deepseek-flash` |
| `SERVICE_TOKEN` | 客户端访问服务的共享口令；未设置时仅允许本机访问 |
| `DATA_DIR` | 任务、上传文件和导出内容的保存位置 |
| `SOFFICE_PATH` | 可选 LibreOffice 可执行文件路径 |
| `MODEL_CONCURRENCY` | 模型调用并发数；模板默认 `3` |

完整模板见 [`server/.env.example`](server/.env.example)。仅保存 Key 不会验证上游账号权限、可用模型或余额。

## 构建与验证

后端测试使用隔离的测试数据及模型替身，无需真实 API Key：

```powershell
Set-Location server
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --frozen
uv run --frozen pytest -q
```

客户端检查：

```powershell
Set-Location app
flutter pub get
flutter analyze
flutter test
```

在项目根目录构建 Windows 或 Android：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Target windows
powershell -ExecutionPolicy Bypass -File .\build.ps1 -Target android
```

脚本会在英文临时路径构建，减少 Windows 原生工具对中文路径的兼容问题。输出分别位于 `dist/windows` 和 `dist/android`。Android 当前使用开发签名，正式分发前需配置自己的签名。

- `build-single-exe.ps1`：使用 PyInstaller 生成 `dist/standalone/ShijuanStudio.exe`。
- `build-installer.ps1 -Compiler <ISCC.exe 路径>`：使用 Inno Setup 生成 Windows 安装程序，需要本机安装 Inno Setup。
- `package.ps1`：根据已有构建目录制作分发包，参数见脚本。

## 项目结构

```text
app/                  Flutter 界面、平台代码与客户端测试
server/
  main.py             API、认证、任务和导出接口
  pipeline.py         文档转换与参考题命题工作流
  brief_generation.py 按要求命题与要求确认
  model.py            DeepSeek 适配、结构验证与重试
  documents.py        文档、公式、图片与 DOCX 处理
  drafts.py           候选版本、修改和导出快照
  reference_search.py 可选联网检索
  desktop_launcher.py 本机桌面后台入口
  tests/              后端测试
installer/            Inno Setup 安装定义
build*.ps1            构建脚本
```

## 数据处理与当前限制

- 文档识别、命题、讨论及可选搜索会调用外部 API，相关材料可能发送给配置的模型服务。使用前确认材料适合发送给该服务；API 使用可能产生费用。
- 单次上传最多 30 个文件、40 页；单文件最大 30 MB，总计最大 100 MB。
- 扫描件无法保证像素级还原；复杂几何、手写批注、表格及跨页内容需人工核对。Word 公式可编辑，配图仍为图片，SVG 源文件作为资源提供。
- 中断后保留已保存内容；服务停止时任务不会继续运行。继续处理是否能复用结果取决于先前保存的阶段。
- 检索来源供参考，不能据此保证全网原创或内容正确；未获取正文的资料会作相应标注。
- `.gitignore` 排除密钥、本地配置、任务数据、原始试卷样例、日志、缓存和构建产物。提交前仍应检查暂存区；配置模板只放空值和公开默认值。
