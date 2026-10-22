# 自定义翻译 API

支持 Gemini 原生接口（AI Studio / Vertex）和 OpenAI 兼容 Chat Completions 接口。API 地址和模型可自行填写；Claude 原生 Messages、OpenAI Responses 等其他协议需要另加适配器，不能仅修改 URL。

## GUI

1. 基本设置选择“Gemini 原生”或“OpenAI 兼容 API”。
2. 在“翻译 API”分别填写 Gemini Key 或自定义 Key。自定义服务还需基础地址，例如 `https://example.com/v1`、`https://example.com/api/v1`，或本地 `http://localhost:1234/v1`。程序只追加 `/chat/completions`。
3. 在高级参数填写服务实际支持的模型名。首次切换到自定义服务时模型留空；当前窗口会分别记住两种服务的模型，保存配置记录当前服务的模型。
4. 默认响应格式选“文本（提示词约束）”。如果服务明确支持 JSON Object 或 JSON Schema，可切换对应模式。
5. “测试翻译”会用固定的公开英文句子向当前服务发起一次请求，不需要先选择媒体，不会写字幕或检查点；它会产生服务费用。预演和本地环境检查均不调用 API。

只有 Gemini Vertex 或 Google Cloud Speech 需要 Google 项目与认证。自定义翻译服务不读取残留的 Gemini backend、项目或凭据文件设置。

## CLI 与配置

完整视频工作流仍安装 `requirements-local.txt`；只使用 OpenAI 兼容 API 翻译 SRT，可仅安装 `requirements-openai.txt`，不需要 Google SDK。

从项目根目录执行（Windows 将 `.venv/bin/python` 换为 `.venv\Scripts\python.exe`）：

```bash
.venv/bin/python main.py examples/hello.en.srt --no_config \
  --translation_provider openai_compatible \
  --api_base_url https://example.com/v1 --model your-model \
  --source_language en --target_language zh-CN --dry_run
```

通过环境变量 `AUTOSUB_API_KEY` 提供自定义服务 Key；去掉 `--dry_run` 执行翻译。不要将真实 Key 放进命令行参数。本地不需要认证的服务可留空 Key，此时不发送 Authorization 头。Gemini 的 `GEMINI_API_KEY` / `GOOGLE_API_KEY` 不会自动用于自定义服务。

可在 `config.json` 中保存以下字段（其余参数使用默认值）：

```json
{
  "translation_provider": "openai_compatible",
  "api_base_url": "https://example.com/v1",
  "model": "your-model",
  "custom_api_key": "",
  "custom_api_key_env": "AUTOSUB_API_KEY",
  "response_format": "text",
  "request_timeout_seconds": 60
}
```

`custom_api_key_env` 可指定其他凭据变量名；CLI 使用该变量的非空值，否则使用保存的 `custom_api_key`。GUI 当前填写的非空 Key 优先于继承的环境变量。`api_key` 继续只用于 Gemini；两个 Key 不自动互换。配置文件是明文，请勿分享。

`request_timeout_seconds` 控制单次请求的网络超时；`translate_timeout_minutes` 是主流水线对整份字幕翻译子进程的总时限。重试次数和请求间隔继续使用 `retries`、`sleep`。遇到 429 时遵循 Retry-After（最多等待 60 秒）；临时服务错误和超时有限重试；认证、模型、请求参数错误直接报告。批量结果格式错误时按原逻辑回退到单条翻译。API 重定向不会被自动跟随。

独立测试服务，不读取个人媒体或 `config.json`：

```bash
.venv/bin/python translate.py --test_connection \
  --translation_provider openai_compatible \
  --api_base_url https://example.com/v1 --model your-model

.venv/bin/python translate.py --test_connection --model gemini-3.8-flash
```

Gemini 测试读取 `GEMINI_API_KEY` / `GOOGLE_API_KEY`。测试模式只请求一次，网络超时最多 30 秒。旧的 `gemini.py --in ... --out ...` 入口仍可用。

## 协议与返回格式

自定义服务收到非流式 `POST {api_base_url}/chat/completions` 请求，包含 `model`、`messages` 和 `stream: false`；Key 非空时使用 `Authorization: Bearer ...`。不会发送 Gemini 专用的 thinking 参数。

- `text`：不发送 `response_format` 参数，由提示词要求返回 JSON 字符串数组，如 `["译文一", "译文二"]`。
- `json_object`：发送 `response_format: {"type":"json_object"}`，要求返回 `{"translations":["译文一","译文二"]}`。
- `json_schema`：发送严格的同结构 JSON Schema，要求返回上述对象。

服务的 HTTP 响应应符合 Chat Completions 结构，译文 JSON 文本放在 `choices[0].message.content`。程序验证数组长度、非空字符串并保留字幕顺序与时间轴，拒绝截断或无效结果。JSON 模式不受支持时会报告错误，应选择服务支持的模式。

## 缓存与扩展

主流水线和翻译器共享同一个翻译身份标识，包含原文哈希、协议、规范化 API 地址、模型、语言、提示词版本和输出相关参数。Vertex 另包含项目与区域。Key、变量名和超时不进入缓存标识，轮换 Key 不触发重新翻译。

更换地址或协议后重新翻译，保留可复用的原文；旧成品按已有备份规则处理。旧版本译文与检查点因标识升级不会盲目复用。

新增协议时在 `translation_providers.py` 添加实现 `translate_lines` / `close` 的适配器，并扩展配置校验、身份标识和 GUI 选项。分批、校验、重试、检查点与字幕输出继续由 `translation_core.py` 维护。

## Turbo 批处理

自定义翻译 API 可与本地 Whisper Turbo 同时使用。GUI 勾选 Turbo，或 CLI 添加 `--turbo --audio_prefetch 2`。翻译仍为单路请求，与音频提取和识别分别推进；鉴权、模型或重试耗尽的限流错误会暂停后续翻译，保留原文及检查点。纯 SRT 输入无需识别模型，普通与 Turbo 使用相同翻译参数与缓存身份。
