# 0.2.0-beta.5

本版修复新公开的 pyasn1 安全问题和月度依赖安装冲突，建议旧版本用户更新源码及已有虚拟环境的依赖。

- pyasn1 从 0.6.4 更新到 0.6.5，修复 CVE-2026-119194、CVE-2026-119195、CVE-2026-119196、CVE-2026-119197 涉及的 ASN.1 解码资源耗尽问题。核心安装入口同步设置最低安全版本。
- 保留 Google GenAI 1.75.0 兼容的 tenacity 9.1.4，修复自动更新到 9.2.1 后锁定依赖无法安装的问题。
- 整合其余 17 项依赖更新，包括 Google Cloud、gRPC、Pydantic、ONNX Runtime 和 certifi；继续保留 filelock 和 eMudhra 证书修复。
- CTranslate2 和 hf-xet 继续使用已验证版本，待完成模型下载及识别验收后单独升级。
- 暂缓 tenacity 的普通次版本更新，保留补丁和安全更新资格。Windows 全套测试、包内 CA 检查和公开漏洞扫描继续作为发布前检查。

本次按受影响包升级，没有将公告中的攻击认定为本应用已复现的问题。依据与依赖兼容性说明见[依赖维护记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.5/docs/DEPENDENCY_MAINTENANCE.md)。

升级请使用新版依赖和锁定文件，步骤见[安装指南](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.5/docs/INSTALLATION.md)。仅替换源码不会更新已有虚拟环境。系统或代理的自定义 CA 由对应环境维护。

此版继续提供 Turbo、Gemini 原生 / Vertex 和自定义 OpenAI 兼容 API。源码 ZIP 和 SHA-256 由通过检查的提交自动生成，不包含个人配置、Key、凭据、虚拟环境或私人媒体。
