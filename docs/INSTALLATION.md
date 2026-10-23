# 安装指南

## Windows 基础环境

1. 安装 64 位 Python 3.13，并保留 Tcl/Tk、Python Launcher。可用 `py -3.13 -m tkinter` 验证界面组件。
2. 下载源码 ZIP 或克隆仓库，解压到可写目录，打开 PowerShell。
3. 执行 `py -3.13 -m venv .venv`。本文直接使用虚拟环境解释器，无需改变 PowerShell 执行策略。
4. 根据任务安装 `requirements-core.txt`、`requirements-local.txt` 或 `requirements-cloud.txt`，例如：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2.2,<27"
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt -c constraints-windows-py313.txt
```

5. 安装系统 FFmpeg，将包含 `ffmpeg.exe`、`ffprobe.exe` 的目录加入 PATH。重新打开终端，检查 `ffmpeg -version`、`ffprobe -version`。仅翻译 SRT 不需要它们。
6. 首次使用复制 `config.json.example` 为 `config.json`；填写 Key，双击 `start_gui.bat`。启动器优先使用本项目 `.venv`，然后使用 Python Launcher 或 PATH 中的 Python。

FFmpeg 来源与安装说明：[FFmpeg 官方下载页](https://ffmpeg.org/download.html)。

仅通过自定义 OpenAI 兼容 API 翻译 SRT 时可安装 `requirements-openai.txt`，无需 Google SDK 或 FFmpeg；完整视频流程仍使用 `requirements-local.txt`。GUI 与 CLI 的服务地址、独立 Key 和模型配置见 [自定义 API 指南](CUSTOM_API.md)。

## 从 0.2.0-beta.2 或更早版本升级

先下载新版源码，保留个人配置，再在新版项目目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2.2,<27"
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements-local.txt -c constraints-windows-py313.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\check_ca_bundles.py
```

仅翻译 SRT 时将依赖文件换成 `requirements-core.txt` 或 `requirements-openai.txt`；Cloud Speech 换成 `requirements-cloud.txt`；安装全部组件使用 `requirements.txt`。此前安装过 Cloud Speech、此次改装 local/core 的环境仍可能保留旧 gRPC，可单独升级该可选组件：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "grpcio>=1.84.1,<2" "grpcio-status>=1.84.1,<2" -c constraints-windows-py313.txt
```

此版要求 certifi 2026.10.19 或更新版本，Cloud Speech 的 gRPC 1.84.1 或更新版本；pip 26.2.2 同时更新其内置 certifi。旧锁定文件会重新安装旧版本，升级时应使用新版文件。应用版本更新本身不会修改已有虚拟环境。

`check_ca_bundles.py` 按 SHA-256 指纹拒绝受 eMudhra 事件影响的 `emSign ECC Root CA - G3`，保留未受影响的 emSign 根。它检查已安装的包内 CA 文件，不修改任何证书。代理或环境变量（如 `SSL_CERT_FILE`、`SSL_CERT_DIR`、`REQUESTS_CA_BUNDLE`、`PIP_CERT`、`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`）指定的信任来源，以及 Windows 系统证书库，需要由对应环境管理者另行更新；仅升级 certifi 不能覆盖它们。可用 `python scripts/check_ca_bundles.py --bundle PATH` 只读检查额外 PEM 文件。保持 TLS 验证开启，不使用 `verify=False` 或 `--trusted-host` 绕过证书问题。

## CPU 与 NVIDIA GPU

先使用 CPU 验证流程：`device=cpu`、`compute_type=int8`；短样例可用 `whisper_model=tiny`。GUI 在 CPU 选择下会把 float16 改为 int8。

faster-whisper 的推理后端是 CTranslate2。GPU 所需 NVIDIA 运行库和版本兼容性按 [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper#gpu)安装，目前其说明列出 CUDA 12 的 cuBLAS 和 cuDNN 9。不同 CTranslate2 版本的要求可能不同，不能用安装 torch 代替这一步。GPU 初始化失败时先切回 CPU，核对驱动、运行库与 PATH。

首次识别会从模型服务下载所选模型；下载、网络和磁盘空间不足会导致首次任务失败。模型缓存通常位于 Hugging Face 缓存目录，不会放进发布包。`tiny` 适合验收流程，正式识别质量请根据素材选择更合适模型。

本版要求 `av<19`，安装依赖时会自动处理。PyAV 19 移除了 faster-whisper 1.2.1 正在使用的 `metadata_errors` 参数；请使用本项目依赖文件，避免单独升级到不兼容版本。[上游记录](https://github.com/PyAV-Org/PyAV/blob/main/CHANGELOG.rst)

## Gemini API Key

在 [Google AI Studio](https://aistudio.google.com/) 创建自己的 Key。应用默认后端 `developer`。Key 可以保存在本机 `config.json` 的 `api_key`，也可以在当前终端设置 `GEMINI_API_KEY`。不要把真实 Key 放进 Issues 或截图。

默认模型可在高级配置的 `model` 字段修改。认证、配额、地区和模型权限报错时检查账户与具体错误；预演不会验证 Key。服务内容规则也可能导致模型拒绝翻译某些素材。

## Cloud Speech 与 Vertex（可选）

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2.2,<27"
.\.venv\Scripts\python.exe -m pip install -r requirements-cloud.txt
```

Cloud Speech 需要启用相关 API 的项目、GCS bucket 和有适当权限的认证。推荐使用 Google Cloud 的 Application Default Credentials，或通过 `GOOGLE_APPLICATION_CREDENTIALS` 指向你本机的凭据文件。不要复制凭据文件到仓库。

Cloud 模式需明确识别语言，如 `source_language=ja`；如果选 `auto`，还需填写 `cloud_language_code`，例如 `ja-JP`。当前实现使用 Speech v1，具体语言与服务支持范围要按实际项目验证。Vertex 翻译额外需要项目和区域，本版区域默认 `global`。

认证参考：[Google Cloud ADC 文档](https://cloud.google.com/docs/authentication/provide-credentials-adc)。本次发布验证不承诺 Cloud Speech 已完成真实账户验收。

## 常见问题

- 启动失败：在终端运行 `.\.venv\Scripts\python.exe gui.py` 查看错误；确认 Python 包与 Tcl/Tk 安装完整。
- FFmpeg 未找到：确认 PATH 后重新打开终端；SRT 翻译可独立测试。
- 字幕来源未知：程序会保留文件。确认可重建后用“备份后重做”；原文 SRT 也可以直接作为输入翻译。
- Key 报错：先核对所选后端、Key、模型权限和配额；不用把 Key 发给维护者。
- 长任务：设置适当翻译超时；失败后保持素材、配置和检查点不变，再次运行。
