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

## 依赖维护

普通依赖升级每月检查，Python 和 GitHub Actions 各合并成一组，同时各保留最多一个普通更新 PR。仅自动提出补丁及次版本更新；主版本升级由维护者单独规划。此限制不用于过滤安全更新，安全漏洞提醒继续保留。PR 不会自动合并。

依赖更新必须同时通过 Windows/Python 3.12、3.13 的常规测试，以及 Python 3.13 的锁定依赖测试。修改锁定文件时，在独立环境验证完整安装组合：

```powershell
py -3.13 -m venv .venv-deps-check
.\.venv-deps-check\Scripts\python.exe -m pip install -r requirements-dev.txt -c constraints-windows-py313.txt
.\.venv-deps-check\Scripts\python.exe -m pip check
.\.venv-deps-check\Scripts\python.exe -m unittest discover -s tests -v
```

关闭日志或模拟 API 的测试无法证明云端服务和模型下载的真实行为，相关依赖升级还需按实际功能验收。主分支要求通过 PR 合并并满足必需检查，不要求额外审批人；禁止强制推送及删除主分支。
