# Turbo 合并交接记录

版本：0.2.0-beta.2。日期：2026-10-22。

以公开主分支 `12fc759674d499159db089a444b9bc9e4bb2cd8a` 为基础，将基于 `79ee5bf` 的独立 Turbo 实现迁入新开发副本。原 Turbo 目录保留未提交的暂存状态，源码未覆盖。

## 最终结构

普通 `pipeline.py` 与 `turbo_scheduler.py` 都使用 `PipelineJob` 的提取、识别、翻译和提交阶段。识别通过共享 `stt_engine.py`，Turbo 使用单个常驻 `stt_worker.py`；普通模式仍按文件调用。`StateStore` 限制调度线程写状态，工作线程只返回结果。

翻译使用主分支已有的 `TranslationConfig`、`translate.py`、`translation_core.py` 和 provider 适配器。任务冻结服务配置并完整传递超时及响应格式。旧 `gemini.py` 保留兼容入口，共用结构化错误报告。翻译身份版本 2 保持不变。

需要机器处理的翻译错误以 `__AUTOSUB_TRANSLATION_ERROR__` 输出原 API 状态；包装异常保留 cause 链。Turbo 对 400/401/403/404/429 暂停后续翻译。通用脱敏覆盖自定义 Key 环境变量。

GUI 保留服务独立模型记忆、两个 Key、API 测试与配置优先级，加入阶段卡片、预取设置、安全停止、回调取消和子进程生命周期管理。

## 验证与后续

完整 136 项测试、独立依赖安装、GPU、真实 Gemini、源码包审查等证据见 [版本验证记录](VALIDATION.md)。旧 Turbo 历史记录保留在 [2026-10-07 验证](TURBO_VALIDATION_20261007.md)。

Windows 上测试 HTTP/1.0 服务快速关闭响应会偶发触发 httpx 的连接重置；对照中 12 次请求只成功 6 次，HTTP/1.1 下 12/12 成功。测试服务改为有 Content-Length 的 HTTP/1.1，并容忍客户端关闭空闲连接；原请求计数、错误重试和字幕断言保留。

如需临时回退运行方式，关闭 Turbo 即可继续使用相同状态与已核验原文。发布回退应通过新的 PR 恢复上一版行为；已有 beta 标签与发布附件保留。

下一阶段优先验证真实长视频的停止等待时间、持续批处理的磁盘与显存占用，以及目标供应商实际响应格式。此次合并不增加 API 并发、单视频切块或多 GPU。
