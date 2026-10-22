"""Provider configuration shared by CLI, GUI, recovery and API adapters."""
from dataclasses import dataclass
import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit

from model_config import DEFAULT_MODEL, DEFAULT_LOCATION

PROVIDERS = ("gemini", "openai_compatible")
RESPONSE_FORMATS = ("text", "json_object", "json_schema")
CUSTOM_KEY_ENV = "AUTOSUB_API_KEY"


def configure_stdio():
    """Keep CLI logs and inherited subprocess pipes readable on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"


def normalize_base_url(value):
    value = str(value).strip()
    try:
        parts = urlsplit(value)
        valid = (parts.scheme in ("http", "https") and parts.hostname
                 and parts.username is None and parts.password is None
                 and not parts.query and not parts.fragment
                 and not re.search(r"[\s\\]", value))
        port = parts.port
        if port == 0:
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("API 地址须为 http(s) 基础地址，且不含账号、密码、查询参数或片段。")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        raise ValueError("请填写 API 基础地址（如 https://example.com/v1），不要包含 /chat/completions。")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port and not (parts.scheme == "https" and port == 443 or parts.scheme == "http" and port == 80):
        host += f":{port}"
    return urlunsplit((parts.scheme, host, path, "", ""))


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = "gemini"
    model: str = DEFAULT_MODEL
    gemini_backend: str = "developer"
    project: str = ""
    location: str = DEFAULT_LOCATION
    api_base_url: str = ""
    custom_api_key_env: str = CUSTOM_KEY_ENV
    response_format: str = "text"

    @classmethod
    def from_values(cls, values):
        get = values.get if isinstance(values, dict) else lambda key, default=None: getattr(values, key, default)
        provider = get("translation_provider", "gemini")
        if provider not in PROVIDERS:
            raise ValueError("无效的翻译服务。")
        model = str(get("model", "") or "").strip()
        if not model and provider == "gemini":
            model = DEFAULT_MODEL
        if not model:
            raise ValueError("请填写翻译模型。")
        backend = get("gemini_backend", "developer")
        if provider == "gemini" and backend not in ("developer", "vertex"):
            raise ValueError("无效的 Gemini 翻译方式。")
        base = normalize_base_url(get("api_base_url", "")) if provider == "openai_compatible" else ""
        key_env = str(get("custom_api_key_env", CUSTOM_KEY_ENV)).strip()
        if provider == "openai_compatible" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
            raise ValueError("Key 环境变量名无效。")
        response_format = get("response_format", "text")
        if response_format not in RESPONSE_FORMATS:
            raise ValueError("无效的响应格式。")
        return cls(provider, model, backend, str(get("project", "") or "").strip(),
                   str(get("location", DEFAULT_LOCATION) or "").strip(), base, key_env, response_format)

    @property
    def vertex(self):
        return self.provider == "gemini" and self.gemini_backend == "vertex"

    @property
    def label(self):
        return "Gemini Vertex" if self.vertex else ("Gemini" if self.provider == "gemini" else "OpenAI 兼容 API")

    def api_key(self, environ=None):
        environ = os.environ if environ is None else environ
        if self.provider == "openai_compatible":
            return environ.get(self.custom_api_key_env, "")
        return environ.get("GEMINI_API_KEY") or environ.get("GOOGLE_API_KEY", "")

    def validate_auth(self, environ=None):
        if self.vertex:
            if not self.project or not self.location:
                raise ValueError("Vertex 翻译需要项目 ID 和区域。")
        elif self.provider == "gemini" and not self.api_key(environ):
            raise ValueError("Gemini API Key 缺失：请在界面填写或设置 GEMINI_API_KEY。")
        # Local OpenAI-compatible servers may deliberately have no authentication.

    def identity_fields(self):
        if self.provider == "gemini":
            from model_config import DEFAULT_THINKING_LEVEL
            return dict(provider=self.provider, backend=self.gemini_backend, model=self.model,
                        project=self.project if self.vertex else "",
                        location=self.location if self.vertex else "",
                        thinking_level=DEFAULT_THINKING_LEVEL)
        return dict(provider=self.provider, api_base_url=self.api_base_url,
                    model=self.model, response_format=self.response_format)

    def cli_arguments(self):
        args = ["--translation_provider", self.provider, f"--model={self.model}"]
        if self.provider == "gemini":
            args += ["--backend", self.gemini_backend]
            if self.vertex:
                args += ["--project", self.project, "--location", self.location]
        else:
            args += ["--api_base_url", self.api_base_url, "--custom_api_key_env", self.custom_api_key_env,
                     "--response_format", self.response_format]
        return args


def credential_environment(config, values, environ=None, *, override=False):
    """GUI edits override inherited keys; CLI environment overrides saved keys."""
    env = dict(os.environ if environ is None else environ)
    if config.provider == "openai_compatible":
        name, saved = config.custom_api_key_env, values.get("custom_api_key", "").strip()
        env["AUTOSUB_ACTIVE_KEY_ENV"] = name
    elif not config.vertex:
        name, saved = "GEMINI_API_KEY", values.get("api_key", "").strip()
        env.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
    else:
        return env
    if saved and (override or not config.api_key(env)):
        env[name] = saved
    if config.provider == "gemini" and env.get("GEMINI_API_KEY"):
        env.pop("GOOGLE_API_KEY", None)
    return env


def redact(message, environ=None):
    env = os.environ if environ is None else environ
    names = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "AUTOSUB_API_KEY", "OPENAI_API_KEY",
             env.get("AUTOSUB_ACTIVE_KEY_ENV", "")}
    result = str(message)
    for secret in sorted({env.get(name) for name in names if env.get(name)}, key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    return result
