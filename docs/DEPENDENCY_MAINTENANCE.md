# 依赖维护记录

## 2026-11-11：本地识别运行库与 gRPC 更新

Windows 锁定依赖将 CTranslate2 从 4.8.2 更新到 4.8.4、hf-xet 从 1.6.0 更新到 1.8.0，grpcio 和 grpcio-status 更新到 1.85.1。保留 pyasn1、filelock、certifi 和 pip 的安全要求，以及依赖审计与包内 CA 检查。

此前受下载网络限制而暂缓的本地识别依赖已完成 [Windows 手动验收](https://github.com/Emrys-Lee-XD/autosub-translator/actions/runs/43046650142)：通过 hf-xet 下载并复用公开 tiny 模型，使用自动设备选择、CPU 的 int8 路径识别公开短音频，生成有效 SRT。该手动作业按需运行，不随普通提交、PR 或定时检查下载模型。GPU 和 `large-v3-turbo` 权重未在本轮验证。

## 2026-11-02：ASN.1 安全更新与月度依赖兼容性

[每周安全扫描](https://github.com/Emrys-Lee-XD/autosub-translator/actions/runs/41487145532)发现 pyasn1 0.6.4 命中四条 ASN.1 解码资源耗尽公告，首次修复版本均为 0.6.5：

- [CVE-2026-119194 / GHSA-fm9c-5rcf-2q5p](https://github.com/advisories/GHSA-fm9c-5rcf-2q5p)：无 schema 解码中的长标签处理。
- [CVE-2026-119195 / GHSA-9m75-vc3g-4x39](https://github.com/advisories/GHSA-9m75-vc3g-4x39)：分片 OCTET STRING、字符串和不定长容器处理。
- [CVE-2026-119196 / GHSA-2qm8-x737-gmw5](https://github.com/advisories/GHSA-2qm8-x737-gmw5)：分片 BIT STRING 的重复移位和复制。
- [CVE-2026-119197 / GHSA-mm57-4v3p-rchx](https://github.com/advisories/GHSA-mm57-4v3p-rchx)：大尾数 ASN.1 REAL 处理。

核心安装入口明确要求 `pyasn1>=0.6.5,<0.7`，Windows 锁定到 0.6.5，使现有 Google 认证传递依赖也必须升级。仅使用 `requirements-openai.txt` 的最小自定义 API 安装不额外引入 ASN.1 依赖。不将公告中的资源耗尽攻击认定为已在本应用复现。

本月 [Dependabot PR #15](https://github.com/Emrys-Lee-XD/autosub-translator/pull/15) 还将 tenacity 升到 9.2.1，但固定的 Google GenAI 1.75.0 元数据要求 `tenacity>=8.2.3,<9.2.0`，导致锁定安装失败。恢复 9.1.4，保留其余 17 项更新。Dependabot 仅暂缓 tenacity 的普通次版本更新；补丁和安全更新继续保留，SDK 接受新范围后应移除此规则。未关闭锁定依赖检查或忽略任何漏洞。

新环境无法连接公开模型的下载 CDN，本轮未完成模型下载与完整 Whisper 推理验收，因此暂缓 CTranslate2 4.8.4 和 hf-xet 1.7.1 两项可选更新，保留已验证的 4.8.2 / 1.6.0。其余更新中的 ONNX Runtime / NumPy 使用包内 Silero VAD 和公开 WAV 进行实际推理验收；tokenizers 使用公开 tiny 分词器进行编码解码验收。GPU、长视频、Cloud Speech 和 Vertex 的真实服务不计入本轮验收范围。

## 2026-10-26：filelock 安全更新

每周安全扫描在 [Actions 40337646164](https://github.com/Emrys-Lee-XD/autosub-translator/actions/runs/40337646164) 正确阻止了包含 `filelock==4.0.7` 的锁定依赖。重新查询全部 53 项锁定依赖，发现以下三条公告，首次修复版本均为 4.2.1：

- [CVE-2026-112940 / GHSA-v4x8-3wr5-3wq8](https://github.com/advisories/GHSA-v4x8-3wr5-3wq8)：POSIX 的 SQLite 读写锁受共享目录中的符号链接和旁路文件影响。
- [CVE-2026-112913 / GHSA-9vhv-jxww-xfm5](https://github.com/advisories/GHSA-9vhv-jxww-xfm5)：Windows 的 SQLite 读写锁会处理其他本地用户放置的旁路文件。
- [CVE-2026-112907 / GHSA-567q-5qvw-pf92](https://github.com/advisories/GHSA-567q-5qvw-pf92)：Windows 软锁标记上的 oplock 可使获取锁超过超时时限。

Windows 锁定到当前 4.x 修复版 4.2.4；`requirements-local.txt` 增加 `filelock>=4.2.1,<5`，避免已有环境的旧传递依赖仍被视为满足要求。filelock 由 Hugging Face 模型缓存使用，项目自己的批处理锁为独立实现。此次按受影响包升级，不声称已在本应用复现公告中的攻击。安全扫描继续保留全部失败条件，无漏洞忽略项。

## 2026-10-23：eMudhra CA 安全更新

certifi 2026.7.22 命中 [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)。共享翻译依赖入口明确要求 `certifi>=2026.10.19`，避免已有环境因传递依赖仍满足要求而停留在旧版本。Windows 锁定值同步更新。

gRPC 使用独立 CA 包。已按 PyPI SHA-256 验证 Windows / CPython 3.13 的 1.84.0、1.84.1 wheel：前者含受影响根，后者已移除。`grpcio` / `grpcio-status` 配对升级到 1.84.1，保留 Protobuf 6.33.6 和现有 Google SDK 版本；[上游安全修复](https://github.com/grpc/grpc/pull/43700)没有在本次 PyPI 包漏洞扫描中被报出，因此 CI 另外检查安装包中的根证书。

安装及 CI 引导使用 `pip>=26.2.2,<27`；[26.2.2](https://github.com/pypa/pip/blob/26.2.2/NEWS.rst) 已内置 certifi 2026.10.19。扫描工具固定 pip-audit 2.10.1，与应用依赖分开安装；每次提交、PR 和每周对完整锁定文件查询公开安全公告。定时扫描不触发发布，main push 必须通过所有 Windows tests 作业（包括安全审计）后才进入发布流程。

包内 CA 检查按真实 DER 指纹识别已知不安全根，使用受影响 G3 与未受影响 G1 的公开证书作回归输入。此检查不替代系统或代理信任库维护，也不能证明不存在未知漏洞。此次升级范围限定为 certifi、gRPC 及安装工具，不包含 PyAV 19、Protobuf 7、Google GenAI 2 等迁移。

## 2026-10-14：PR #10 协同迁移

PR #10 的四项 Google 依赖升级均要求 `protobuf>=6.33.5`，不能与首发锁定的 Protobuf 5 共用。此次人工安排迁移，将核心依赖范围改为 `protobuf>=6.33.5,<7`，并锁定 `protobuf==6.33.6`；Protobuf 7 仍需另行验收。新增的传递依赖 `opentelemetry-api` 同步锁定到完整安装验证使用的 1.45.1。

保留 `pydantic==2.13.5` 与它要求的 `pydantic-core==2.46.5` 配对，撤销独立升级 core 到 2.49.0 的提议。仅存在 Windows/Python 3.13 wheel，并不能证明 core 与上层 Pydantic 版本兼容。

验证包括完整锁定依赖安装、`pip check`、全部现有测试，以及仓库要求的 Windows/Python 3.12、3.13 常规检查和 Windows/Python 3.13 锁定检查。Gemini 的请求配置、默认模型与 `thinking_level` 保持现有测试覆盖；这些检查不调用付费云端 API，也不验证真实项目的云端权限。

上游依据：[Pydantic 2.13.5 精确 core 依赖](https://github.com/pydantic/pydantic/blob/v2.13.5/pyproject.toml)、[grpcio-status 1.84.0 的 Protobuf 要求](https://github.com/grpc/grpc/blob/v1.84.0/src/python/grpcio_status/setup.py)、[Google API Core 变更记录](https://googleapis.dev/python/google-api-core/latest/CHANGELOG.html)。

## 2026-09-30：首发后的维护记录

首发后 Dependabot 创建了 7 个普通升级 PR。

## 检查结果

初次 CI 仅按依赖范围安装，未使用 `constraints-windows-py313.txt`，因此不能核验锁定文件中的实际组合。新增独立 Windows/Python 3.13 任务，用锁定文件安装全部开发依赖，再执行 `pip check` 和完整测试。

在新建环境中尝试 #3 的 proto-plus 1.28.4 与 #5 的 googleapis-common-protos 1.75.4；两者均要求 protobuf >=6.33.5，与本项目的 protobuf <6 及锁定的 5.29.6 冲突。安装器分别返回 ResolutionImpossible，因此两项补丁升级也暂缓。

还原原锁定组合后，新环境完整安装成功，`pip check` 与 73 项测试通过。

## 原有 PR 的处理策略

| PR | 变更 | 处理 |
|---|---|---|
| #1、#2 | GitHub Actions 6 → 7 | 关闭普通升级提议，大版本迁移人工安排 |
| #3、#5 | Google 辅助库补丁版本 | 关闭不兼容的提议，保留当前锁定组合 |
| #4 | protobuf 5 → 7 | 关闭，需同时规划相关依赖迁移 |
| #6 | grpcio-status 1.71.2 → 1.84.0 | 关闭，目标版本要求 protobuf >=6.33.5 |
| #7 | huggingface-hub 1 → 2 | 关闭，大版本需验证真实模型下载 |

这些 PR 是普通版本更新提议；关闭它们不会更改已发布的 v0.1.0-beta.1 标签或下载包。后续安全提醒继续保留，安全修复单独评估。

## 后续规则

- 普通升级按月检查，每个生态分成一个组，各最多一个未关闭的普通更新 PR。
- 仅自动提出补丁和次版本升级，主版本升级由维护者规划；`allow.update-types` 仅过滤版本更新，不过滤安全更新。
- 所有合并都需经过 PR，且通过常规 Python 3.12/3.13 与锁定 Python 3.13 检查。不启用自动合并。
- 主分支禁止强制推送及删除，规则适用于管理员；不要求额外审批人。

参考：[Dependabot 配置选项](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)、[proto-plus 1.28.4 的官方依赖](https://pypi.org/pypi/proto-plus/1.28.4/json)、[googleapis-common-protos 1.75.4 的官方依赖](https://pypi.org/pypi/googleapis-common-protos/1.75.4/json)。
