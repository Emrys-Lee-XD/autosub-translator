"""API adapters; SDKs are imported only when the selected provider needs them."""
from typing import Protocol
from translation_core import (ResponseFormatError, parse_translations, retry_after_seconds,
                              short_error, translation_prompt)


class TranslationProvider(Protocol):
    def translate_lines(self, lines: list[str], source_language: str = "auto",
                        target_language: str = "zh-CN") -> list[str]: ...

    def close(self) -> None: ...


class ProviderError(RuntimeError):
    def __init__(self, message, status_code, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class GeminiProvider:
    def __init__(self, config, *, timeout=60, client=None):
        self.config = config
        if client is None:
            from google import genai
            from google.genai import types
            options = types.HttpOptions(timeout=max(1, int(timeout * 1000)),
                                        retry_options=types.HttpRetryOptions(attempts=1))
            if config.vertex:
                client = genai.Client(vertexai=True, project=config.project,
                                      location=config.location, http_options=options)
            else:
                client = genai.Client(vertexai=False, api_key=config.api_key(), http_options=options)
        self.client = client

    def translate_lines(self, lines, source_language="auto", target_language="zh-CN"):
        from google.genai import types
        from model_config import DEFAULT_THINKING_LEVEL
        response = self.client.models.generate_content(
            model=self.config.model,
            contents=translation_prompt(lines, source_language, target_language),
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=list[str],
                thinking_config=types.ThinkingConfig(thinking_level=DEFAULT_THINKING_LEVEL)),
        )
        return parse_translations(response.text, len(lines))

    def close(self):
        self.client.close()


class OpenAICompatibleProvider:
    def __init__(self, config, *, timeout=60):
        import httpx
        self.config = config
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)

    def translate_lines(self, lines, source_language="auto", target_language="zh-CN"):
        object_response = self.config.response_format != "text"
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": translation_prompt(
                lines, source_language, target_language, object_response=object_response)}],
            "stream": False,
        }
        if self.config.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif self.config.response_format == "json_schema":
            body["response_format"] = {
                "type": "json_schema", "json_schema": {
                    "name": "subtitle_translations", "strict": True,
                    "schema": {"type": "object", "properties": {
                        "translations": {"type": "array", "items": {"type": "string"}}},
                        "required": ["translations"], "additionalProperties": False}}}
        headers = {}
        key = self.config.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        response = self.client.post(self.config.api_base_url + "/chat/completions",
                                    json=body, headers=headers)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json().get("error", {})
                message = error.get("message", "") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                message = ""
            message = str(message).replace(key, "[REDACTED]") if key else message
            raise ProviderError(f"API HTTP {response.status_code}: {short_error(message) if message else '请求失败'}",
                                response.status_code, retry_after_seconds(response.headers.get("retry-after")))
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
            if choice.get("finish_reason") == "length":
                raise ResponseFormatError("模型输出被截断，请减少每批字幕条数。")
            if message.get("refusal"):
                raise ResponseFormatError("翻译服务拒绝了请求。")
            content = message["content"]
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            raise ResponseFormatError("API 响应缺少有效的 choices[0].message.content。") from exc
        return parse_translations(content, len(lines), object_response=object_response)

    def close(self):
        self.client.close()


def create_provider(config, *, timeout=60) -> TranslationProvider:
    config.validate_auth()
    if config.provider == "gemini":
        return GeminiProvider(config, timeout=timeout)
    return OpenAICompatibleProvider(config, timeout=timeout)
