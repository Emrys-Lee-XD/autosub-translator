# Autosub 多语言字幕工作台

将视频转写成字幕，再使用 Gemini 翻译；也可以直接翻译已有 SRT。提供中文桌面界面、命令行、源/目标语言选择、双语或纯译文输出、断点恢复和批量处理。

当前版本：**0.1.0-beta.1**，Windows 源码测试版。项目使用 AI 辅助开发，测试范围见 [验证记录](docs/VALIDATION.md)。

## 安装与启动

推荐 Windows 10/11、64 位 Python 3.13。Python 安装时启用 Tcl/Tk 和 Python Launcher。CPU 可以运行本地识别；NVIDIA GPU 的安装说明见 [安装指南](docs/INSTALLATION.md)。

在项目目录打开 PowerShell：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt -c constraints-windows-py313.txt
Copy-Item config.json.example config.json
```

复制配置只需做一次；已有个人配置时直接编辑它。安装系统 FFmpeg，并确认 `ffmpeg -version`、`ffprobe -version` 可运行。本项目使用外部 FFmpeg 提取视频音频。

双击 `start_gui.bat`，输入你自己的 Google AI Studio API Key，选择素材与语言。点击“保存配置”记住设置；“预演”只检查处理流程，“开始生成”执行任务。源语言默认自动识别，目标语言默认简体中文。选中基本或高级页签后，文字和留白会放大。

首次本地识别会下载 Whisper 模型。没有显卡或希望先快速试用时，可选 CPU、`tiny` 模型、`int8` 精度；更大模型需要更多时间和内存。

`constraints-windows-py313.txt` 记录本次 Windows/Python 3.13 已验证的依赖组合，只约束版本，不会额外安装云端或开发包。其他 Python 版本可以省略 `-c`，但需自行验证。

### 不同任务需要什么

| 任务 | 安装依赖 | 需要的配置 |
|---|---|---|
| 翻译已有 SRT | `requirements-core.txt` | Gemini API Key |
| 本地视频识别与翻译 | `requirements-local.txt` | Gemini API Key；Whisper 模型和设备 |
| Google Cloud Speech 识别与翻译 | `requirements-cloud.txt` | Key、Cloud Project、GCS bucket、Cloud 认证、识别语言 |
| 全部功能 | `requirements.txt` | 根据实际任务填写 |

默认 AI Studio 翻译和本地识别无需在应用中填写 Cloud Project。高级 Vertex 翻译仍需要项目及认证。安装及认证详情见 [安装指南](docs/INSTALLATION.md)。

## 配置

公开仓库只提供 `config.json.example`。`config.json` 是你本机的配置，含 Key 时是明文文件，请妥善保管。GUI 启动会加载它，“加载配置”重新读取，“保存配置”写回；未保存的界面修改也会用于当前任务。

CLI 默认读取项目目录的 `config.json`；`--config other.json` 指定另一份配置，`--no_config` 使用内置默认值和命令行参数。命令行参数覆盖配置；`GEMINI_API_KEY` 环境变量优先于 CLI 配置里的 Key。Cloud 凭据也可由 `GOOGLE_APPLICATION_CREDENTIALS` 指定。

示例中所有 Key、项目、bucket 和凭据路径都为空。数字字段可用 JSON 数字或字符串；语言可使用预设列表或其他合法语言标签，如 `pt-BR`、`nl`。语言标签合法不保证识别服务或模型支持它。

## 命令行与示例

```powershell
.\autosub.bat "examples\hello.en.srt" --source_language en --target_language zh-CN --dry_run
.\autosub.bat "examples\hello.en.srt" --source_language en --target_language it --output_mode translated
.\autosub.bat "D:\Videos\sample.mp4" --source_language auto --target_language en
.\autosub.bat "D:\Videos" --source_language ja --target_language zh-CN
```

文件夹入口递归处理视频；已有字幕用单个 SRT 入口翻译。公开示例和生成短测试视频的方法见 [examples](examples/README.md)。

## 输出与恢复

- 原文：`sample.source.原语言.srt`。
- 译文：`sample.目标语言.bilingual.srt` 或 `sample.目标语言.translated.srt`。最终译文在 Windows 中默认可见。
- SRT 翻译在原文件名后追加目标语言和输出方式，保留输入文件。
- 状态和日志写在素材目录的 `.autosub_state.json`、`.autosub_progress.jsonl`；检查点在 `.autosub_checkpoints`，临时文件在 `.autosub_work`。这些内部文件可为隐藏状态。

程序按素材、识别参数、原文、翻译配置和成品哈希核验结果；参数改变后会备份已知旧成品再处理。来源未知的同名字幕会保留并报错，选择“备份后重做”或 `--force` 后重建。强制重做会绕过旧译文缓存和当前任务的翻译检查点。

翻译失败会保留可续跑的原文和检查点；重新运行同一任务即可继续。“重试无文字视频”用于重新识别此前没有文本的素材。停止按钮等待当前素材完成后停止。`--no_progress_log` 只关闭日志，保留恢复状态。

## 数据与费用

字幕文本会发给所选 Gemini 服务。Google Cloud Speech 会把音频上传到所配 GCS bucket，并在识别操作后尝试删除临时对象；本地 Whisper 的识别在本机执行。服务费用、配额、模型权限由你自己的账户决定。Key、Cloud 凭据及包含私人素材信息的日志应留在本机。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q -x '[\\/]\.venv[\\/]' .
.\.venv\Scripts\python.exe -m pip check
```

Windows CI 会在提交和拉取请求时运行测试、编译及发布文件检查。CI 使用模拟服务，不需要个人 Key。其他平台、长视频和 Cloud Speech 的真实验收范围见 [验证记录](docs/VALIDATION.md)。

本版提供源码 ZIP，运行需要 Python 和依赖。许可证为 [MIT](LICENSE)，更新记录见 [CHANGELOG](CHANGELOG.md)，问题反馈和安全说明见 [贡献指南](CONTRIBUTING.md)及 [SECURITY](SECURITY.md)。
