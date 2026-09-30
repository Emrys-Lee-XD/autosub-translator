# 更新记录

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
