#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import math
import sys
import time
import os
import gc
import traceback
import uuid
from pathlib import Path
from typing import List, Dict
from language_config import join_words

class Log:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    DIM = "\033[2m"

CONSERVATIVE_HALLUCINATION_PHRASES = {
    "Subtitles by", "Thank you for watching", "Amara.org",
    "ご視聴ありがとうございました", "チャンネル登録",
    "字幕制作", "字幕提供", "字幕翻译提供", "字幕制作提供",
    "谢谢观看", "感谢观看", "请点赞", "请订阅",
}

AGGRESSIVE_HALLUCINATION_PHRASES = [
    "Subtitles by", "字幕制作", "未经作者授权", "点赞", "订阅", "Subscribe", 
    "Thank you for watching", "观看更多视频", "Amara.org", "MBC", "TBS",
    "ご視聴ありがとうございました", "チャンネル登録", "高評価", "字幕提供", "字幕协力", "字幕翻译", "字幕制作协力", "字幕制作提供", "谢谢观看", "请点赞", "请订阅", "感谢观看", "更多视频", "字幕由", "字幕翻译提供", "字幕制作提供",
    "下期见", "敬请期待", "敬请期待下一集", "敬请期待下期", "敬请期待下集", "敬请期待下一回", "敬请期待下回", "敬请期待后续", "敬请期待续集", "敬请期待后续内容", "敬请期待后续更新", "敬请期待后续发展", "敬请期待后续剧情", "敬请期待后续故事", "敬请期待后续事件"]

def format_timestamp(seconds: float) -> str:
    total_millis = max(0, int(round(seconds * 1000)))
    whole_seconds, millis = divmod(total_millis, 1000)
    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    secs = whole_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def write_srt(segments: List[Dict], path: str) -> None:
    print(f"   Writing SRT file -> {path}...")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            count = 1
            for seg in segments:
                # 最后的清洗：去掉空内容
                text = seg['text'].strip()
                if not text: continue
                
                f.write(f"{count}\n")
                f.write(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n")
                f.write(text + "\n\n")
                count += 1
        os.replace(tmp, output)
        print(f"   {Log.GREEN}SRT write success.{Log.RESET}")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"   {Log.RED}Failed to write SRT: {e}{Log.RESET}")
        raise

def segment_words(words: List[Dict], max_chars: int, max_dur: float, gap: float, language="ja") -> List[Dict]:
    segments = []
    current = []
    current_start = None
    current_end = None

    def flush() -> None:
        nonlocal current, current_start, current_end
        if current:
            segments.append({"start": current_start, "end": current_end, "text": join_words(current, language)})
        current = []
        current_start = None
        current_end = None

    for word in words:
        text = str(word["word"])
        start = float(word["start"])
        end = float(word["end"])
        if current:
            projected_chars = len(join_words(current + [text], language))
            projected_duration = end - current_start
            silence_gap = start - current_end
            if projected_chars > max_chars or projected_duration > max_dur or silence_gap > gap:
                flush()
        if not current:
            current_start = start
        current.append(text)
        current_end = end

    flush()
    return segments

def run_google_stt(gcs_uri: str, lang: str, timeout: float, max_chars: int, max_dur: float, gap: float,
                   project="") -> List[Dict]:
    from google.cloud import speech_v1 as speech
    import google.auth

    print(f"   Waiting for Google STT (may take a while)...")
    credentials, _ = google.auth.default(quota_project_id=project or None)
    client = speech.SpeechClient(credentials=credentials)
    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        language_code=lang,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=True,
        model="latest_long",
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        audio_channel_count=1,
    )
    op = client.long_running_recognize(config=config, audio=audio)
    resp = op.result(timeout=int(timeout * 3600))
    words = []
    for result in resp.results:
        if not result.alternatives: continue
        alt = result.alternatives[0]
        for w in alt.words:
            words.append({"word": w.word, "start": w.start_time.total_seconds(), "end": w.end_time.total_seconds()})
    if not words: raise RuntimeError("No words returned from Google STT")
    
    return segment_words(words, max_chars=max_chars, max_dur=max_dur, gap=gap, language=lang)

def normalized_phrase(text: str) -> str:
    return text.strip().strip("。.!！?？…・-—~～").casefold()

CONSERVATIVE_NORMALIZED_PHRASES = frozenset(
    normalized_phrase(item) for item in CONSERVATIVE_HALLUCINATION_PHRASES
)

def is_hallucination(text: str, mode: str = "conservative") -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if mode == "off":
        return False

    normalized = normalized_phrase(stripped)
    if normalized in CONSERVATIVE_NORMALIZED_PHRASES:
        return True
    if mode != "aggressive":
        return False

    for bad_word in AGGRESSIVE_HALLUCINATION_PHRASES:
        if bad_word.casefold() in stripped.casefold():
            return True
    if stripped.startswith("(") and stripped.endswith(")"): return True
    if stripped.startswith("（") and stripped.endswith("）"): return True
    if stripped.startswith("[") and stripped.endswith("]"): return True
    return False

def is_near_duplicate(previous: Dict, text: str, start: float, window_seconds: float) -> bool:
    if not previous or previous.get("text", "").strip() != text.strip():
        return False
    return start <= float(previous.get("end", 0.0)) + window_seconds

def run_local_whisper_and_save(
    audio_path: str,
    out_path: str,
    model_size: str,
    device: str,
    compute_type: str,
    hallucination_filter: str,
    dedupe_window_seconds: float,
    initial_prompt: str,
    source_language: str = "ja",
) -> None:
    from stt_engine import load_model, transcribe_one
    config = dict(model_size=model_size, device=device, compute_type=compute_type,
                  hallucination_filter=hallucination_filter,
                  dedupe_window_seconds=dedupe_window_seconds,
                  initial_prompt=initial_prompt, source_language=source_language)
    print(f"   Loading Whisper ({model_size})...", flush=True)
    model = load_model(config)
    print("   Model loaded. Transcribing...", flush=True)
    summary = transcribe_one(model, audio_path, out_path, config,
        lambda data: print(f"   Recognized {data['seconds']:.1f}s / {data['duration']:.1f}s", flush=True))
    print(f"   Transcribed {summary['segments']} segments. Language: {summary['language']}")
    del model
    gc.collect()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed

def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed

def non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["google", "local"], default="google")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="ja-JP")
    ap.add_argument("--source_language", default="ja")
    ap.add_argument("--project", default="")
    ap.add_argument("--timeout_hours", type=positive_float, default=3.0)
    ap.add_argument("--max_chars", type=positive_int, default=25)
    ap.add_argument("--max_duration", type=positive_float, default=6.0)
    ap.add_argument("--gap", type=non_negative_float, default=0.5)
    ap.add_argument("--model_size", default="large-v3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute_type", default="float16")
    ap.add_argument("--hallucination_filter", choices=["off", "conservative", "aggressive"], default="conservative")
    ap.add_argument("--dedupe_window_seconds", type=non_negative_float, default=0.1)
    ap.add_argument("--initial_prompt", default="")
    args = ap.parse_args()

    print(f"   [sub.py] Starting... Input: {args.input}")

    if args.method == "google":
        segments = run_google_stt(args.input, args.lang, args.timeout_hours, args.max_chars, args.max_duration, args.gap, args.project)
        write_srt(segments, args.out)
    else:
        run_local_whisper_and_save(
            args.input,
            args.out,
            args.model_size,
            args.device,
            args.compute_type,
            args.hallucination_filter,
            args.dedupe_window_seconds,
            args.initial_prompt,
            args.source_language,
        )

if __name__ == "__main__":
    main()
