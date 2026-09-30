# 参与开发

欢迎提交修复、文档改进和可复现的问题。请说明 Windows/Python 版本、任务入口、识别方式、所选模型、具体报错和已做的排查；删去 Key、项目标识、个人文件路径与素材内容。

请使用可公开的短素材或人工 SRT 复现。提交前运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m pip check
```

涉及恢复、备份、文件覆盖或云端调用的修改应提供对应回归测试。测试不要读取个人配置、调用付费服务或使用私人媒体。GUI 在 Windows 上有真实 Tk 事件循环测试；新的平台支持需单独验收。

项目使用 AI 辅助开发。提交者仍需理解修改并验证结果，PR 中写清问题、改变后的行为、测试及实际限制。提交内容按本项目 MIT 许可证贡献。
