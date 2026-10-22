# 版本验证记录

## 0.1.0-beta.1 历史验证

验证日期：2026-09-30。环境：Windows、64 位 Python 3.13.6，独立新建的虚拟环境。

## 已完成

- 根据公开依赖文件重新安装依赖，没有复用全局 Python 包。最终安装组合记录在 `constraints-windows-py313.txt`。
- 完整 73 项自动化测试通过，包括真实 Tk 事件循环、配置读写、GUI/CLI 参数传递、缓存与身份验证、翻译失败恢复、强制重做、关闭日志后状态复用、成品可见性以及公开 WAV 解码。
- `pip check` 通过。
- 发布文件检查工具已具备凭据文件、常见 Key 和私钥标记、个人配置、非公开媒体检查。测试覆盖意外加入个人配置、文档中出现 Key 的情况。
- Windows CI 配置完成 YAML 结构检查；引用的 Actions SHA 已从官方仓库核对。远端 CI 需在用户决定发布后运行。
- CLI `--version` 返回 `0.1.0-beta.1`。
- Python 源码编译检查通过。
- 52 个待提交公开文件通过发布检查；临时源码 ZIP 包含这 52 个文件及 `MANIFEST.sha256`，逐文件哈希校验通过。额外按本机实际 Key 逐项扫描 ZIP 内容，未发现该 Key，也未包含个人配置、凭据、虚拟环境或 Git 历史。
- 源码 ZIP 解压到独立临时目录后，使用新虚拟环境执行完整 73 项测试，全部通过。

## 真实短视频验收

用 Windows 本地合成语音生成公开英文 WAV，再用系统 FFmpeg 合成短视频。测试在临时素材目录运行，使用 CPU、Whisper tiny、int8，识别模型从模型服务下载。

1. FFmpeg 提取音频成功。
2. Whisper 本地识别生成 1 条英文字幕。
3. 使用用户自己的 Key，经 Gemini Developer API 生成 1 条中英双语字幕。
4. `--no_progress_log` 未创建日志，但保留状态；再次执行同一任务返回成功并复用已核验成品。

识别文本：

> Hello. This is a subtitle translation test. You can choose the source and target languages.

译文：

> 你好，这是一次字幕翻译测试，你可以选择源语言和目标语言。

Key 只用于测试进程环境，没有复制到公开源码目录或样例。公开样例为合成素材。

## 本次发现并修复的依赖问题

按未约束的依赖范围安装时，PyAV 19 与 faster-whisper 1.2.1 不兼容，`av.open(metadata_errors=...)` 报错。加入 `av<19` 后安装 PyAV 18.1.0，真实识别与翻译通过；新增不需要模型或 Key 的真实 WAV 解码测试，便于 CI 检测此类问题。

参考：[PyAV 上游变更记录](https://github.com/PyAV-Org/PyAV/blob/main/CHANGELOG.rst)。

## 边界

此次证据覆盖 Windows/Python 3.13、新虚拟环境、公开英文短样例、CPU/tiny 和一次 Gemini 真翻译。它不能代表真实长视频、复杂对话、多语种准确率、所有模型权限、GPU、Cloud Speech、Vertex 或其他操作系统均已验收。

CI 将包含 Python 3.12 和 3.13 的 Windows 任务；Python 3.12 远端任务尚未执行。仓库与源码 ZIP 发布之前，应复核实际待提交文件并运行发布检查工具。

## 2026-10-22：0.2.0-beta.1 自定义 API 验证

本次环境为 Debian 13、Python 3.12.14；GUI 通过 Xvfb 使用真实 Tk 事件循环。

- 完整 103 项测试：102 项通过，1 项 Windows batch 启动器测试按平台跳过。
- 原有 Gemini 回归覆盖保留；另外使用官方 Google SDK 和模拟 HTTP 传输验证原生请求序列化、模型参数及译文解析，没有调用真实 Gemini 服务。
- OpenAI 兼容接口使用本地 HTTP 服务验证真实请求路径、Bearer 认证、三种响应模式、429 / 503 / 超时处理、认证错误停止重试、无效译文拒绝、批量失败回退单条、检查点续跑与服务地址隔离。
- 更换翻译服务地址时复用已生成的视频原文；GUI 服务切换、独立 Key、模型切换和单次 API 测试按钮通过真实事件循环验证。
- Gemini 与自定义服务的 CLI 预演、`pip check`、源码编译和 `git diff --check` 通过。
- 发布审查修复端口为 0 的地址被改为默认端口的问题，并将该输入加入地址校验回归测试。
- 发布审查复现非 UTF-8 终端中的中文日志编码错误，统一 CLI 和翻译子进程输出编码，并用 `PYTHONIOENCODING=cp1252` 的真实 HTTP 翻译工作流验证修复。
- Windows CI 进一步发现共享引擎的中文重试日志会受调用方输出编码影响，以及检查点测试未显式按 UTF-8 读取文件。已修复两处问题；新增非 UTF-8 日志流的真实 HTTP 重试回归测试，保留检查点内容及续跑断言。
- 在临时源码目录构建包含新增模块的源码 ZIP；全部 61 个候选源码文件通过发布审查，ZIP 和逐文件清单哈希验证通过。

随后环境发布并成功注入个人 `GEMINI_API_KEY`，完成以下真实服务验收；Key 仅通过运行环境使用，没有写入源码、配置或测试记录：

- Gemini 原生接口：使用 `gemini-3.8-flash` 翻译公开 `examples/hello.en.srt` 的 2 条字幕，生成中英双语成品，核对条数、原文、时间轴及中文译文均正确。再次运行复用已核验成品。
- OpenAI 兼容接口：使用同一 Gemini Key，显式指定 `custom_api_key_env=GEMINI_API_KEY`，通过官方 `https://generativelanguage.googleapis.com/v1beta/openai` 的 Chat Completions 端点和 `text` 响应模式再次翻译上述 2 条字幕。切换接口时正确备份原生成品，译文、时间轴及第二次运行的缓存复用均通过。

上述验收只调用 Gemini 服务。其他供应商、OpenAI 兼容接口的真实 JSON Object / JSON Schema 模式仍以本地 HTTP 集成测试为证据。Windows 自动化测试结果见发布 PR 的 CI 检查；GPU 和实际模型下载不在本次验证范围。

## 2026-10-22：0.2.0-beta.2 Turbo 合并验证

- 在独立目录从当前公开主分支迁入 Turbo，没有修改原 Turbo 的源码、暂存区或个人配置。
- Windows、Python 3.13.6，新建虚拟环境，按 `requirements-dev.txt` 与 `constraints-windows-py313.txt` 安装；Protobuf 6.33.6、grpcio-status 1.84.0；`pip check` 通过。
- 合并版完整 **136 项测试通过**（51.812 秒），包括原两套回归及 5 项交叉集成测试。交叉测试通过真实翻译子进程验证自定义 API 三种响应格式、SRT 不加载识别模型、401/403/404/429 暂停翻译而继续模拟 STT、Key 脱敏、Key 轮换、服务切换、模式切换与旧入口错误码；自定义 SRT 路径还验证不导入 Google SDK。
- 本地 HTTP 测试服务改为 HTTP/1.1，解决 Windows 快速关闭 HTTP/1.0 响应导致的偶发连接重置；未放宽请求次数或错误重试断言。
- 真实 FFmpeg、RTX 5080（驱动 621.01）、Whisper large-v3 / CUDA float16：3 个公开合成短视频全部生成双语字幕，模型初始化 1 次；每个成品通过条数、原文与时间轴核验，未遗留 WAV。
- 这组 Turbo 用时 13.34 秒；随后普通模式约 0.18 秒核验并复用全部成品，没有重复请求翻译。另一个独立普通任务实际识别并翻译相同短素材，约 10.31 秒，原文 SRT 与 Turbo 对应结果字节一致。这些时间受已缓存模型和短素材影响，不能直接比较为长视频加速倍数。
- 上述 GPU 流程的翻译使用本地 HTTP 模拟服务；随后单独以实际 Gemini Key 和配置模型，在普通与 Turbo 模式分别翻译公开 `hello.en.srt` 的 2 条字幕（约 4.85 / 3.60 秒），输出通过源文、条数、时间轴核验。Key 仅经进程环境传递，没有进入源码或命令行。
- GUI 由真实 Tk 事件循环测试覆盖 API 测试按钮、服务/模型切换、Turbo 控件、Cloud Speech 切换、配置保存及阶段进度。

范围限制：本次真实 GPU 素材均为公开英文合成短视频；未将用户长视频、持续大批量、多语种质量、Cloud Speech、Vertex、其他 GPU 或真实第三方供应商作为已验收结果。发布后远端 Windows CI 和附件核验由发布记录补充。
