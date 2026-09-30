# 本地发布准备与人工发布

版本：0.1.0-beta.1。源码包名称：`autosub-translator-0.1.0-beta.1-source.zip`。

## 检查与打包

```powershell
git status --short
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
git add .
.\.venv\Scripts\python.exe scripts\release_audit.py
.\.venv\Scripts\python.exe scripts\build_source_release.py
```

发布工具读取已加入 Git 的文件，审查工作目录内容并要求没有未暂存的变更。源码 ZIP 默认生成在忽略的 `dist` 目录，包含文件哈希清单，并附带 ZIP 的 SHA-256 文件。同名包已存在时会报错，避免意外覆盖。

检查 ZIP：只应包含公开源码、测试、依赖、文档、配置示例、MIT 许可证和公开样例；不能含 `.git`、`.venv`、个人 `config.json`、真实凭据或任务文件。解压到独立临时目录，再运行测试或预演。

## 用户决定发布后

1. 设置真实的 Git 作者姓名与邮箱，仅在需要时使用仓库级配置。
2. 创建初始提交；确认暂存区与源码包一致。
3. 在用户自己的 GitHub 账号下创建公开仓库，设置 `origin`，推送 `main`。
4. 检查 Windows Actions 结果，并启用可用的 secret scanning、push protection、Dependabot alerts 和私密漏洞反馈。
5. 为验证过的提交创建 `v0.1.0-beta.1` 标签；创建标记为预发布的 Release，使用 `docs/RELEASE_NOTES.md`，附上源码 ZIP 与 SHA-256。

这些步骤需要用户明确的发布指令。仓库不含自动推送、自动发布 Release 或上传包的脚本；CI 只做检查及本地打包。

## 许可证与贡献

采用 MIT，署名 `Autosub contributors`。项目使用 AI 辅助开发，维护者负责审核和验证代码。名称、署名和版本可在发布前调整；调整后需重新运行检查并生成对应源码包。
