# 0.2.0-beta.1

Autosub 新增自定义 OpenAI 兼容翻译 API，支持填写基础地址、模型和独立 Key，同时保留 Gemini AI Studio / Vertex、中文 GUI 与命令行。

- 自定义接口支持 Chat Completions、文本 / JSON Object / JSON Schema 响应模式、单次请求超时和有限重试。
- GUI 新增翻译服务切换与“测试翻译”按钮；Key 按服务分别配置，支持通过环境变量提供。测试按钮发送一次固定公开文本请求，可能产生服务费用。
- 翻译引擎统一管理分批、结果校验、检查点与字幕输出；旧配置和 `gemini.py` 入口继续兼容。
- 缓存区分服务协议、API 地址、模型及语言。切换服务时复用原文，已知旧成品会备份后重新翻译。
- 修复端口为 0 的自定义地址被错误改为默认端口的问题。
- 修复非 UTF-8 终端中的中文日志编码错误，命令行和翻译子进程统一输出 UTF-8。

升级说明：本版升级了翻译身份标识，旧译文和翻译检查点不会直接复用，可能产生一次重新翻译请求；原文仍按已有核验规则复用。首次切换自定义服务时，请填写该服务支持的模型名。

安装：阅读 README、安装指南和 `docs/CUSTOM_API.md`。完整视频流程使用 `requirements-local.txt`；仅通过 OpenAI 兼容服务翻译 SRT，可安装 `requirements-openai.txt`。源码包不含 Key、Cloud 凭据、虚拟环境或私人媒体。

验证：Debian / Python 3.12 的 102 项自动化测试中，101 项通过，1 项 Windows 启动器测试按平台跳过；Gemini 原生与官方 OpenAI 兼容端点均完成真实短字幕翻译、时间轴和缓存复用验证。其他供应商及 JSON 响应模式有本地 HTTP 集成测试覆盖。详细证据见 `docs/VALIDATION.md`。

这是源码预发布版。长视频、GPU、Cloud Speech、Vertex 和其他供应商的真实账户行为尚未全面验收。
