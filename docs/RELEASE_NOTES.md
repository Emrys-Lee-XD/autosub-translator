# 0.1.0-beta.1

Autosub 的首个 Windows 源码测试版，提供中文桌面界面与命令行，用于视频转写和多语言 SRT 翻译。

支持 API Key 驱动的 Gemini 翻译、Whisper 本地识别、可选 Cloud Speech 与 Vertex；支持 JSON 配置、双语或纯译文、文件夹任务、安全备份及翻译断点恢复。

本版修复了配置覆盖、无文字重试、翻译失败续跑和强制重做复用缓存的问题；关闭日志时仍保留恢复状态。最终译文默认可见。

安装：阅读 README 与安装指南，创建 Python 虚拟环境，安装依赖，复制配置示例并填写自己的 Key。源码包不含用户 Key、Cloud 凭据、虚拟环境或私人媒体。

具体测试证据与未覆盖范围见 `docs/VALIDATION.md`。这是预发布版，尚不承诺长视频、GPU、Cloud Speech 和跨平台行为的全面验收。
