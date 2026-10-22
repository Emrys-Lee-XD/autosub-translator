# 0.2.0-beta.2

Autosub 合入 Turbo 批量处理，同时保留上一版的 Gemini 原生 / Vertex、自定义 OpenAI 兼容 API、独立 Key、响应格式及单次请求超时。

- 本地 Whisper 在同一批次中常驻，配合单路音频预取与独立翻译队列。默认预取 2，可设为 1～4；公开配置默认关闭 Turbo。
- GUI 增加 Turbo 开关、音频预取与三个阶段状态；安全停止等待当前阶段落盘，下次从已完成阶段继续。普通模式保留，Cloud Speech 继续使用普通流程。
- 普通与 Turbo 共用翻译配置、缓存身份和字幕提交校验。切换服务或地址重新翻译，切换模式、轮换 Key 保留可复用结果。
- 统一子进程错误码与自定义 Key 脱敏。鉴权、模型或重试耗尽的限流错误暂停后续翻译，识别可以继续；保留原文和检查点。
- 修复 Tk 窗口销毁后的延迟回调，并保留子进程树清理、进程重启上限和音频完成证明。

验证：Windows / Python 3.13.6 全部 136 项测试通过；干净安装的锁定依赖通过依赖检查。RTX 5080、Whisper large-v3 / float16 实际完成 3 个公开合成短视频，模型加载 1 次，普通模式复用成功；独立普通识别的原文与 Turbo 一致。Gemini 普通 / Turbo 均实际翻译了公开的 2 条字幕，核验时间轴、条数与原文通过。自定义 API 的三种响应模式、鉴权失败暂停和 Key 隔离通过本地 HTTP 与真实翻译子进程验证。详见 [验证记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.2/docs/VALIDATION.md)。

这是 Windows 源码预发布版，需要 Python、依赖和系统 FFmpeg。安装见 [README](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.2/README.md)。源码 ZIP 不含个人配置、Key、凭据、虚拟环境或私人媒体。

长视频、持续大批量、多语种识别质量、其他 GPU、Cloud Speech、Vertex 及其他供应商的真实账户行为尚未全面验收。短样例结果不代表长视频性能承诺。
