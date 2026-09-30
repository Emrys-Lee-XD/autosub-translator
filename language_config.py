"""Language, output and recovery identities shared by CLI and GUI."""
import hashlib
import json
import re
from pathlib import Path
from model_config import DEFAULT_THINKING_LEVEL

LANGUAGES = {
    "ja": "日语", "en": "英语", "zh-CN": "简体中文", "zh-TW": "繁体中文",
    "ko": "韩语", "fr": "法语", "de": "德语", "it": "意大利语", "es": "西班牙语",
}
SPEECH_CODES = {"ja": "ja-JP", "en": "en-US", "zh-CN": "cmn-Hans-CN",
                "zh-TW": "cmn-Hant-TW", "ko": "ko-KR", "fr": "fr-FR",
                "de": "de-DE", "it": "it-IT", "es": "es-ES"}
PROMPT_VERSION = 1
OUTPUT_VERSION = 1


def language_tag(value, *, allow_auto=False):
    value = str(value).strip()
    if value == "auto" and allow_auto:
        return value
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", value):
        raise ValueError(f"Invalid language tag: {value!r}")
    return value


def language_label(value):
    return LANGUAGES.get(value, value)


def normalized_text(text, language):
    """Preserve Latin word boundaries while joining East Asian subtitle lines."""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if language.startswith(("ja", "zh", "cmn", "yue")) or (language == "auto" and
        sum(bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", line)) for line in lines) > len(lines) / 2):
        return "".join(lines)
    return " ".join(lines)


def join_words(words, language):
    if language.startswith(("ja", "zh", "cmn", "yue")):
        return "".join(words)
    text = ""
    for word in words:
        part = str(word).strip()
        if not part:
            continue
        if not text or part[0] in ",.!?:;%)]}，。！？；：、" or text[-1] in "([{¿¡":
            text += part
        else:
            text += " " + part
    return text


def identity(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stt_identity(args):
    mode = getattr(args, "stt_mode", "local")
    fields = {"version": 1, "mode": mode, "language": getattr(args, "source_language", "auto")}
    if mode == "local":
        fields.update(model=getattr(args, "whisper_model", "large-v3"),
                      device=getattr(args, "device", "auto"),
                      compute_type=getattr(args, "compute_type", "default"),
                      hallucination_filter=getattr(args, "hallucination_filter", "off"),
                      dedupe_window_seconds=getattr(args, "dedupe_window_seconds", 0.1),
                      initial_prompt=getattr(args, "initial_prompt", ""))
    else:
        fields.update(bucket=getattr(args, "bucket", ""), project=getattr(args, "project", ""),
                      cloud_language_code=getattr(args, "cloud_language_code", ""))
    return identity(fields)


def translation_identity(args, source_hash):
    return identity({"version": 1, "prompt": PROMPT_VERSION, "source_sha256": source_hash,
                     "source_language": getattr(args, "source_language", "auto"),
                     "target_language": getattr(args, "target_language", "zh-CN"),
                     "backend": getattr(args, "gemini_backend", "developer"),
                     "model": getattr(args, "model", ""),
                     "thinking_level": DEFAULT_THINKING_LEVEL})


def output_identity(args, source_hash):
    return identity({"version": OUTPUT_VERSION,
                     "translation": translation_identity(args, source_hash),
                     "mode": getattr(args, "output_mode", "bilingual")})


def source_path(video, language):
    video = Path(video)
    return video.with_name(f"{video.stem}.source.{language}.srt")


def output_path(source, language, mode):
    source = Path(source)
    stem = source.stem if source.suffix.lower() != ".srt" else source.name[:-4]
    return source.with_name(f"{stem}.{language}.{mode}.srt")
