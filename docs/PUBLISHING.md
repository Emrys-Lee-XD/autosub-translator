# 版本发布流程

当前版本：0.2.0-beta.1。源码包名称：`autosub-translator-0.2.0-beta.1-source.zip`。

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

## GitHub 发布

1. 核对现有 Git 作者配置，更新 `version.py`、README、更新记录和发布说明中的版本号。
2. 在当前仓库创建发布分支并提交审核过的源码；确认源码包与该提交逐文件一致。
3. 推送发布分支，创建指向 `main` 的 PR。主分支要求 PR 合并，不直接推送或绕过保护规则。
4. 等待 Windows / Python 3.12、3.13 和锁定依赖检查通过，再合并 PR。保持可用的 secret scanning、push protection、Dependabot alerts 和私密漏洞反馈设置。
5. 核对合并提交与待发布源码一致，为该提交创建 `v0.2.0-beta.1` 标签；使用 `docs/RELEASE_NOTES.md` 创建预发布 Release，附上源码 ZIP 与 SHA-256。
6. 从 Release 下载附件，复核 ZIP、SHA-256、逐文件清单及标签对应的 Git 提交。

发布需要用户明确的发布指令。仓库不含自动推送、自动发布 Release 或上传包的脚本；CI 只做检查及本地打包。GitHub API 与附件上传分别需要访问 `api.github.com`、`uploads.github.com`。

## 许可证与贡献

采用 MIT，署名 `Autosub contributors`。项目使用 AI 辅助开发，维护者负责审核和验证代码。名称、署名和版本可在发布前调整；调整后需重新运行检查并生成对应源码包。
