# 0.2.0-beta.4

本版修复每周依赖扫描发现的 filelock 安全问题，建议 0.2.0-beta.3 及更早版本用户更新源码及本地识别虚拟环境的依赖。

- Windows 锁定的 filelock 从 4.0.7 更新到 4.2.4，修复 CVE-2026-112940、CVE-2026-112913、CVE-2026-112907。
- 本地识别安装入口明确要求 `filelock>=4.2.1,<5`，避免已有环境继续使用旧的模型缓存锁依赖。
- 保留 beta.3 的 eMudhra 证书修复、包内 CA 检查和每周公开漏洞审计。

三条公告涉及共享目录中的本地文件攻击或 Windows 软锁阻塞，升级针对受影响依赖；本次没有将公告中的攻击认定为本应用已复现的问题。详情与上游链接见[依赖维护记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.4/docs/DEPENDENCY_MAINTENANCE.md)。

升级请使用新版依赖和锁定文件，步骤见[安装指南](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.4/docs/INSTALLATION.md)。仅替换源码不会更新已有虚拟环境。系统或代理的自定义 CA 仍由对应环境维护。

此版继续提供 Turbo、Gemini 原生 / Vertex 和自定义 OpenAI 兼容 API。Windows tests 的全部测试及依赖安全作业通过后，发布流程才会生成源码 ZIP 和 SHA-256；附件不包含个人配置、Key、凭据、虚拟环境或私人媒体。
