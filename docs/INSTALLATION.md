# 安装指南

## Windows 基础环境

1. 安装 64 位 Python 3.13，并保留 Tcl/Tk、Python Launcher。可用 `py -3.13 -m tkinter` 验证界面组件。
2. 下载源码 ZIP 或克隆仓库，解压到可写目录，打开 PowerShell。
3. 执行 `py -3.13 -m venv .venv`。本文直接使用虚拟环境解释器，无需改变 PowerShell 执行策略。
4. 根据任务安装 `requirements-core.txt`、`requirements-local.txt` 或 `requirements-cloud.txt`，例如：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt -c constraints-windows-py313.txt
```

5. 安装系统 FFmpeg，将包含 `ffmpeg.exe`、`ffprobe.exe` 的目录加入 PATH。重新打开终端，检查 `ffmpeg -version`、`ffprobe -version`。仅翻译 SRT 不需要它们。
6. 首次使用复制 `config.json.example` 为 `config.json`；填写 Key，双击 `start_gui.bat`。启动器优先使用本项目 `.venv`，然后使用 Python Launcher 或 PATH 中的 Python。

FFmpeg 来源与安装说明：[FFmpeg 官方下载页](https://ffmpeg.org/download.html)。

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
