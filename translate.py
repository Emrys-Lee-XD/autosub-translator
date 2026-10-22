#!/usr/bin/env python3
"""Common translator entry point for Gemini and OpenAI-compatible APIs."""
import argparse
import os
import sys

from language_config import language_tag
from srt_utils import read_srt
from translation_config import (CUSTOM_KEY_ENV, PROVIDERS, RESPONSE_FORMATS,
                                TranslationConfig, credential_environment)
from translation_core import (non_negative_float, positive_int, retry_translation,
                              run_translation, save_checkpoint, short_error)
from translation_providers import create_provider


def positive_float(value):
    parsed = non_negative_float(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main(argv=None, *, gemini_batch=None, checkpoint_saver=save_checkpoint):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp")
    parser.add_argument("--out")
    parser.add_argument("--test_connection", action="store_true", help="translate a fixed public sentence (one API request)")
    parser.add_argument("--translation_provider", choices=PROVIDERS, default="gemini")
    parser.add_argument("--api_base_url", default="")
    parser.add_argument("--custom_api_key_env", default=CUSTOM_KEY_ENV)
    parser.add_argument("--response_format", choices=RESPONSE_FORMATS, default="text")
    parser.add_argument("--backend", "--gemini_backend", dest="gemini_backend",
                        choices=("developer", "vertex"), default="developer")
    parser.add_argument("--project", default="")
    parser.add_argument("--location", default="global")
    parser.add_argument("--model", default="")
    parser.add_argument("--source_language", default="auto")
    parser.add_argument("--target_language", default="zh-CN")
    parser.add_argument("--output_mode", choices=("bilingual", "translated"), default="bilingual")
    parser.add_argument("--batch", type=positive_int, default=20)
    parser.add_argument("--sleep", type=non_negative_float, default=1)
    parser.add_argument("--line_retries", type=positive_int, default=3)
    parser.add_argument("--request_timeout_seconds", type=positive_float, default=60)
    parser.add_argument("--checkpoint")
    args = parser.parse_args(argv)
    try:
        config = TranslationConfig.from_values(args)
        config.validate_auth()
        args.model = config.model
        args.api_base_url = config.api_base_url
        args.source_language = language_tag(args.source_language, allow_auto=True)
        args.target_language = language_tag(args.target_language)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.test_connection and (not args.inp or not args.out):
        parser.error("--in and --out are required unless --test_connection is used")
    blocks = None if args.test_connection else read_srt(args.inp)
    if blocks == []:
        parser.error("input SRT contains no subtitles")
    os.environ.update(credential_environment(config, {}))
    timeout = min(args.request_timeout_seconds, 30) if args.test_connection else args.request_timeout_seconds
    provider = create_provider(config, timeout=timeout)
    try:
        def translate_batch(lines):
            if gemini_batch is not None and config.provider == "gemini":
                return gemini_batch(provider.client, args.model, lines, args.line_retries, args.sleep,
                                    args.source_language, args.target_language)
            return retry_translation(lambda: provider.translate_lines(lines, args.source_language, args.target_language),
                                     args.line_retries, args.sleep)
        if args.test_connection:
            result = provider.translate_lines(["Hello. This is a subtitle translation test."], "en", args.target_language)
            print(f"API 测试通过：{config.label} / {config.model}\n译文：{result[0]}")
        else:
            run_translation(args, blocks, translate_batch, checkpoint_saver=checkpoint_saver)
    finally:
        provider.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Translation failed: {short_error(exc)}", file=sys.stderr)
        sys.exit(1)
