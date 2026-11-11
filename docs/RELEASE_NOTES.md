# 0.2.0-beta.6

本版收录 SRT 兼容性、模型预设和界面手册改进，并更新本地识别与云端依赖。

- SRT 支持逗号或点号毫秒分隔符，以及 UTF-8、带 BOM 的 UTF-16、GB18030 和 Big5 等编码。自动检测遇到 GB18030 / Big5 歧义时会提示选择；已知编码时可以在界面或命令行直接指定，原字幕文件会保留。
- 高级设置提供可编辑的翻译模型、Whisper 模型及计算精度建议，包括 `large-v3-turbo`。设备设为自动且没有 CUDA 时，`float16` 会回退到 CPU 的 `int8`。
- 更新 Gemini 推荐模型，修复加载配置后服务模型建议不刷新的问题。已有自定义模型配置仍可使用，模型建议也可自行编辑。
- 界面新增“使用手册”入口，遇到无法打开浏览器时会显示提示。
- Windows 锁定的 CTranslate2 更新到 4.8.4、hf-xet 更新到 1.8.0，grpcio 和 grpcio-status 更新到 1.85.1；保留已有安全依赖与 CA 检查。可按需运行 Windows 公开 tiny 模型下载、缓存及 CPU 识别验收。

已通过真实 Gemini 短字幕翻译和 Windows 公开 tiny 模型 CPU 识别验收；本轮没有验收 GPU、`large-v3-turbo` 权重、Vertex 或真实第三方供应商。测试范围和详细记录见[验证记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.6/docs/VALIDATION.md)及[依赖维护记录](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.6/docs/DEPENDENCY_MAINTENANCE.md)。

升级请使用新版依赖和锁定文件，步骤见[安装指南](https://github.com/Emrys-Lee-XD/autosub-translator/blob/v0.2.0-beta.6/docs/INSTALLATION.md)。仅替换源码不会更新已有虚拟环境。系统或代理的自定义 CA 由对应环境维护。

源码 ZIP 和 SHA-256 校验文件由通过检查的提交自动生成。
