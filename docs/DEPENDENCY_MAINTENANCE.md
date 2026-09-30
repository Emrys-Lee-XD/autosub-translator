# 依赖维护记录

日期：2026-09-30。首发后 Dependabot 创建了 7 个普通升级 PR。

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
