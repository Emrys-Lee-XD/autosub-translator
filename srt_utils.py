"""Strict, shared SRT parsing without cloud dependencies."""
import re
from pathlib import Path

TIME = r"\d{2,}:[0-5]\d:[0-5]\d,\d{3}"
HEADER = re.compile(rf"({TIME})\s*-->\s*({TIME})")


def milliseconds(value):
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def read_srt(path):
    data = Path(path).read_text(encoding="utf-8-sig").strip()
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
        if milliseconds(end) <= milliseconds(start):
            raise ValueError("SRT end must be after start")
        text = "\n".join(lines[2:]).strip()
        if not text or any("-->" in line for line in lines[2:]):
            raise ValueError("Empty text or missing block separator")
        blocks.append((str(index), start, end, text))
        previous_index = index
    return blocks
