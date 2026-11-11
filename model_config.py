"""Shared defaults for GUI, command line and translator."""

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_LOCATION = "global"
DEFAULT_THINKING_LEVEL = "LOW"

# Upgrade the previous application default when an older GUI settings file is loaded.
LEGACY_DEFAULT_MODELS = {"gemini-3.1-flash-lite"}

RECOMMENDED_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)

RECOMMENDED_OPENAI_MODELS = (
    "gpt-4o-mini",
    "gpt-4o",
    "deepseek-chat",
    "qwen-plus",
)

RECOMMENDED_WHISPER_MODELS = (
    "large-v3-turbo",
    "large-v3",
    "medium",
    "small",
    "base",
    "tiny",
)

RECOMMENDED_COMPUTE_TYPES = (
    "default",
    "float16",
    "int8",
    "float32",
)
