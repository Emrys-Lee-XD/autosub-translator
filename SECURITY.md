# 安全与私人数据

当前维护版本：0.2.0-beta.4。此源码测试版提供本地配置和用户自己的云服务接入。

0.2.0-beta.4 将本地识别依赖明确要求为 `filelock>=4.2.1,<5`，Windows 锁定到 4.2.4，修复 CVE-2026-112940、CVE-2026-112913、CVE-2026-112907。这些公告涉及共享目录中的本地文件攻击或 Windows 软锁超时阻塞；包版本受影响不代表已确认应用可被利用。公告及验证记录见[依赖维护记录](docs/DEPENDENCY_MAINTENANCE.md)。

0.2.0-beta.3 修复 eMudhra 事件涉及的 Python 依赖信任：要求 `certifi>=2026.10.19`，Cloud Speech 要求 `grpcio` / `grpcio-status>=1.84.1`，安装引导使用 `pip>=26.2.2,<27`。0.2.0-beta.2 及更早版本的锁定文件包含受影响版本，请使用新版本的依赖文件升级已有虚拟环境。来源：[certifi 公告](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)、[gRPC 1.84.1](https://github.com/grpc/grpc/releases/tag/v1.84.1)。

CI 对锁定依赖执行漏洞审计，并用 `python scripts/check_ca_bundles.py` 检查 certifi、gRPC 和 pip 自带的实际 CA 包。该工具只读，可用 `--bundle PATH` 额外检查指定 PEM 文件。系统信任库、代理及环境变量指定的 CA 包由运行环境管理；升级 Python 包不会自动更新这些信任来源，程序不改写它们或关闭 TLS 验证。详情见[安装指南](docs/INSTALLATION.md)。

`config.json` 明文保存 API Key。Cloud 服务账户文件、`.env`、私人字幕/视频和任务日志不应提交。公开仓库只包含空凭据的配置示例和人工创建的样例。

发布脚本会检查实际 Git 文件清单中的常见凭据文件与秘密标记；这不能替代人工审查。创建远端仓库后应启用可用的 secret scanning 和 push protection。若真实 Key 或服务账户已泄露，先撤销或轮换凭据，再处理公开文件与历史。

报告安全问题时使用仓库提供的私密漏洞报告功能；若该功能尚未启用，可先提交不包含利用细节、凭据或私人数据的 Issue，请求私密联系渠道。请不要在公开 Issue 上传 Key、凭据 JSON 或私人素材。

本地 Whisper 识别在本机执行；翻译向所选 Gemini 或自定义 API 服务发送字幕文本。自定义 API 只使用为它配置的 Key，不自动使用 Gemini Key；设置 API 地址即选择字幕与该 Key 的接收方。Cloud Speech 使用所选项目和 GCS bucket 处理音频。维护者不会提供公共 Key，CI 不需要个人云服务凭据。
