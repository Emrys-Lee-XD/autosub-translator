# 0.2.0-beta.3

本版修复 eMudhra 证书事件影响的 Python HTTPS 依赖，建议 0.2.0-beta.2 及更早版本用户更新源码及已有虚拟环境。

- 所有翻译入口要求 `certifi>=2026.10.19`，Windows 锁定版本同步更新。
- Cloud Speech 使用的 `grpcio` / `grpcio-status` 更新到 1.84.1，修复 gRPC 独立证书库中的受影响根。
- 安装与 CI 引导使用 pip 26.2.2 或更新的 26.x，更新 pip 内置 certifi 及已有安全修复。
- CI 检查实际安装包的 CA 内容；新增针对受影响及未受影响 emSign 根、损坏证书包和只读诊断的回归测试。
- 完整锁定依赖在提交、PR 和每周接受公开漏洞审计；发布等待包括安全作业在内的 Windows tests 全部通过。

升级时请使用新版依赖和锁定文件；仅替换源码不会更新已有虚拟环境。步骤见[安装指南](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.3/docs/INSTALLATION.md)。系统、代理或环境变量指定的自定义 CA 信任需要由对应环境维护，升级 Python 包不会改写这些证书库。证书诊断工具可只读检查额外 PEM 文件，TLS 验证保持开启。

此版继续提供 Turbo、Gemini 原生 / Vertex 和自定义 OpenAI 兼容 API。依赖升级范围限定为 certifi、gRPC 和 pip，验证记录见[依赖维护记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.3/docs/DEPENDENCY_MAINTENANCE.md)。

上游依据：[certifi 安全公告](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)、[gRPC 1.84.1](https://github.com/grpc/grpc/releases/tag/v1.84.1)、[pip 26.2.2](https://github.com/pypa/pip/blob/26.2.2/NEWS.rst)。

这是 Windows 源码预发布版。源码 ZIP 和 SHA-256 由通过检查的提交生成，不包含个人配置、Key、凭据、虚拟环境或私人媒体。
