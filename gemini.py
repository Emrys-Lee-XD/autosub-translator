#!/usr/bin/env python3
"""Backward-compatible Gemini entry point; shared translation lives in translate.py."""
import sys

from srt_utils import read_srt
from translation_config import TranslationConfig
from translation_core import (ResponseFormatError, clean_json_markdown, load_checkpoint,
                              non_negative_float, positive_int, retry_translation,
                              save_checkpoint, short_error, source_sha256, report_error,
                              write_bilingual_srt, write_translated_srt)
from translation_providers import GeminiProvider


def __getattr__(name):
    # Preserve existing imports without requiring Google's SDK for other providers.
    if name == "genai":
        from google import genai
        return genai
    if name == "types":
        from google.genai import types
        return types
    raise AttributeError(name)


def gemini_translate_lines(client, model, ja_lines, source_language="ja", target_language="zh-CN"):
    return GeminiProvider(TranslationConfig(model=model), client=client).translate_lines(
        ja_lines, source_language, target_language)


def translate_with_retries(client, model, lines, attempts, sleep_seconds,
                           source_language="ja", target_language="zh-CN"):
    return retry_translation(lambda: gemini_translate_lines(client, model, lines, source_language, target_language),
                             attempts, sleep_seconds)


def main():
    from translate import main as translate_main
    return translate_main(gemini_batch=translate_with_retries, checkpoint_saver=save_checkpoint)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        report_error(exc)
        sys.exit(1)
