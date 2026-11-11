import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from language_config import translation_identity
from model_config import (DEFAULT_MODEL, RECOMMENDED_GEMINI_MODELS, RECOMMENDED_OPENAI_MODELS,
                          RECOMMENDED_WHISPER_MODELS, RECOMMENDED_COMPUTE_TYPES)
from srt_utils import read_srt, read_srt_text


class SrtEnhancementTests(unittest.TestCase):
    def test_read_srt_supports_dot_millisecond_timestamps(self):
        content = "1\n00:00:01.500 --> 00:00:04.200\nHello world\n\n2\n00:00:04.500 --> 00:00:06.800\nSecond line\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write(content)
            path = Path(tmp.name)
        try:
            blocks = read_srt(path)
            self.assertEqual(len(blocks), 2)
            self.assertEqual(blocks[0], ("1", "00:00:01,500", "00:00:04,200", "Hello world"))
            self.assertEqual(blocks[1], ("2", "00:00:04,500", "00:00:06,800", "Second line"))
        finally:
            path.unlink(missing_ok=True)

    def test_read_srt_supports_gb18030_encoding(self):
        text = "1\n00:00:00,000 --> 00:00:01,000\n测试中文字幕\n\n"
        with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
            tmp.write(text.encode("gb18030"))
            path = Path(tmp.name)
        try:
            blocks = read_srt(path, encoding="gb18030")
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0][3], "测试中文字幕")
        finally:
            path.unlink(missing_ok=True)

    def test_read_srt_supports_utf16_encoding(self):
        text = "1\n00:00:00,000 --> 00:00:01,000\nUTF-16 字幕测试\n\n"
        with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
            tmp.write(text.encode("utf-16"))
            path = Path(tmp.name)
        try:
            blocks = read_srt(path)
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0][3], "UTF-16 字幕测试")
        finally:
            path.unlink(missing_ok=True)

    def test_ambiguous_chinese_encodings_are_never_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.srt"
            for codec, text in (("big5", "中文"), ("gb18030", "测试中文字幕")):
                with self.subTest(codec=codec):
                    path.write_bytes(("1\n00:00:00,000 --> 00:00:01,000\n" + text + "\n").encode(codec))
                    with self.assertRaisesRegex(ValueError, "字幕编码无法自动确定"):
                        read_srt(path)
                    self.assertEqual(read_srt(path, encoding=codec)[0][3], text)

    def test_unambiguous_gb18030_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.srt"
            text = "字幕𠀀"
            path.write_bytes(("1\n00:00:00,000 --> 00:00:01,000\n" + text + "\n").encode("gb18030"))
            with self.assertRaises(UnicodeDecodeError):
                path.read_bytes().decode("big5")
            self.assertEqual(read_srt(path)[0][3], text)

    def test_explicit_big5_handles_bytes_that_also_form_valid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.srt"
            path.write_bytes(("1\n00:00:00,000 --> 00:00:01,000\n价\n").encode("big5"))
            self.assertEqual(read_srt(path)[0][3], "ɲ")  # Auto mode prefers UTF-8.
            self.assertEqual(read_srt(path, encoding="big5")[0][3], "价")

    def test_bomless_utf16_requires_explicit_byte_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.srt"
            text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n"
            for codec in ("utf-16-le", "utf-16-be"):
                with self.subTest(codec=codec):
                    path.write_bytes(text.encode(codec))
                    with self.assertRaisesRegex(ValueError, "UTF-16"):
                        read_srt(path)
                    self.assertEqual(read_srt(path, encoding=codec)[0][3], "Hello")


class ModelConfigEnhancementTests(unittest.TestCase):
    def test_recommended_models_include_turbo_and_mainstream_models(self):
        self.assertIn("large-v3-turbo", RECOMMENDED_WHISPER_MODELS)
        self.assertIn("large-v3", RECOMMENDED_WHISPER_MODELS)
        self.assertIn("gemini-3.8-flash", RECOMMENDED_GEMINI_MODELS)
        self.assertIn("gemini-2.5-flash", RECOMMENDED_GEMINI_MODELS)
        self.assertIn("gpt-4o-mini", RECOMMENDED_OPENAI_MODELS)
        self.assertIn("float16", RECOMMENDED_COMPUTE_TYPES)
        self.assertIn("int8", RECOMMENDED_COMPUTE_TYPES)
        self.assertNotIn("gemini-1.5-flash", RECOMMENDED_GEMINI_MODELS)
        self.assertNotIn("gemini-1.5-pro", RECOMMENDED_GEMINI_MODELS)

    def test_default_encoding_preserves_existing_translation_identity(self):
        args = SimpleNamespace(model="test-model")
        old = translation_identity(args, "source-hash")
        args.srt_encoding = "auto"
        self.assertEqual(translation_identity(args, "source-hash"), old)
        args.srt_encoding = "big5"
        big5 = translation_identity(args, "source-hash")
        args.srt_encoding = "gb18030"
        self.assertNotEqual(translation_identity(args, "source-hash"), big5)
        self.assertNotEqual(big5, old)


class ManualTests(unittest.TestCase):
    @patch("webbrowser.open")
    def test_manual_opens_readme_html(self, mock_open):
        import manual
        manual.main()
        self.assertTrue(mock_open.called)
        uri = mock_open.call_args[0][0]
        self.assertTrue(uri.startswith("file:///"))

    def test_manual_reports_browser_failure_and_cleans_temporary_file(self):
        import manual
        create_file = manual.NamedTemporaryFile
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(manual, "NamedTemporaryFile",
                             side_effect=lambda *a, **kw: create_file(*a, dir=tmp, **kw)), \
                patch("webbrowser.open", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "无法启动浏览器"):
                manual.main()
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
