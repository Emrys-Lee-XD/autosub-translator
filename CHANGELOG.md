# 更新记录

## 0.2.0-beta.1 — 2026-10-22

- 新增自定义 OpenAI 兼容 Chat Completions 接口，支持 API 地址、模型、独立 Key、JSON 输出格式和单次请求超时配置。
- 翻译流程抽离为共享引擎，保留 Gemini AI Studio / Vertex 和旧 `gemini.py` 入口；GUI 增加服务切换与单次测试翻译。
- 缓存与检查点统一按服务协议、API 地址、模型和语言区分，切换服务复用原文，旧译文按备份规则重新生成。
- 拒绝端口为 0 的 API 地址，避免地址规范化时错误改用默认端口。
- 命令行及翻译子进程统一使用 UTF-8 输出，修复 Windows 非 UTF-8 终端中中文日志导致任务失败的问题。
- 普通依赖更新改为每月分组，每个生态最多一个更新 PR；主版本升级人工安排，保留安全提醒。
- CI 增加 Windows/Python 3.13 的完整锁定依赖安装、依赖检查和完整测试。
- 验证依赖更新时发现 proto-plus 1.28.4、googleapis-common-protos 1.75.4 与当前 protobuf 范围冲突，暂缓升级。
- 主分支维护流程要求 PR 与测试通过，禁止强制覆盖和删除。

## 0.1.0-beta.1

- 首个 Windows 源码测试版，中文 GUI 与命令行。
- 本地 Whisper、可选 Google Cloud Speech、Gemini Developer API/Vertex。
- 多语言、已有 SRT 翻译、双语或纯译文、文件夹批量处理。
- 个人 JSON 配置加载/保存，界面未保存的修改立即用于当前任务。
- 基于素材与配置身份的成品复用、失败后续跑和安全备份。
- 修复无文字重试、首次翻译失败后续跑、强制重做复用旧译文等问题。
- 修复 `--no_progress_log` 关闭恢复状态的问题。
- 最终译文在 Windows 默认可见，内部状态和工作文件可隐藏。
- 新增干净发布目录、公开示例、Windows CI 和源码发布包审查工具。
- 约束 PyAV 版本低于 19，避免 faster-whisper 1.2.1 的音频解码参数不兼容。
