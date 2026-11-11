"""Strict, shared SRT parsing without cloud dependencies."""
import codecs
import re
from pathlib import Path

TIME = r"\d{2,}:[0-5]\d:[0-5]\d[,.]\d{3}"
HEADER = re.compile(rf"({TIME})\s*-->\s*({TIME})")
SRT_ENCODINGS = ("auto", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "gb18030", "big5")


def milliseconds(value):
    value = str(value).replace(".", ",")
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def read_srt_text(path, *, encoding="auto"):
    """Decode subtitles without silently guessing between ambiguous legacy encodings."""
    if encoding not in SRT_ENCODINGS:
        raise ValueError(f"不支持的字幕编码：{encoding}")
    raw = Path(path).read_bytes()

    def decode(codec):
        try:
            return raw.decode(codec).removeprefix("\ufeff")
        except UnicodeError as exc:
            raise ValueError(f"字幕无法按 {encoding if encoding != 'auto' else codec} 解码，请检查字幕编码。") from exc

    if encoding != "auto":
        text = decode("utf-8-sig" if encoding == "utf-8" else encoding)
    elif raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise ValueError("不支持 UTF-32 字幕，请先转换为 UTF-8。")
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            candidates = []
            for codec in ("gb18030", "big5"):
                try:
                    candidate = raw.decode(codec)
                except UnicodeDecodeError:
                    continue
                if "\x00" not in candidate:
                    candidates.append(candidate)
            if not candidates:
                raise ValueError("无法识别字幕编码，请选择正确的字幕编码或转换为 UTF-8。") from None
            if len(set(candidates)) != 1:
                raise ValueError("字幕编码无法自动确定；请选择 GB18030 或 Big5，或将字幕转换为 UTF-8。") from None
            text = candidates[0]
    if "\x00" in text:
        raise ValueError("字幕包含空字符；无 BOM 的 UTF-16 字幕请选择 UTF-16-LE 或 UTF-16-BE。")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def read_srt(path, *, encoding="auto"):
    data = read_srt_text(path, encoding=encoding)
    if not data:
        raise ValueError("Empty SRT")
    blocks = []
    previous_index = 0
    for chunk in re.split(r"\n[ \t]*\n", data):
        lines = chunk.strip().splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError("Malformed SRT block")
        index = int(lines[0].strip())
        match = HEADER.fullmatch(lines[1].strip())
        if not match or index <= previous_index:
            raise ValueError("Invalid SRT index or timestamp")
        start, end = match.groups()
        start = start.replace(".", ",")
        end = end.replace(".", ",")
        if milliseconds(end) <= milliseconds(start):
            raise ValueError("SRT end must be after start")
        text = "\n".join(lines[2:]).strip()
        if not text or any("-->" in line for line in lines[2:]):
            raise ValueError("Empty text or missing block separator")
        blocks.append((str(index), start, end, text))
        previous_index = index
    return blocks
