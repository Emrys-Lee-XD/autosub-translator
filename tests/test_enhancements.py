import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            blocks = read_srt(path)
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


class ModelConfigEnhancementTests(unittest.TestCase):
    def test_recommended_models_include_turbo_and_mainstream_models(self):
        self.assertIn("large-v3-turbo", RECOMMENDED_WHISPER_MODELS)
        self.assertIn("large-v3", RECOMMENDED_WHISPER_MODELS)
        self.assertIn("gemini-3.8-flash", RECOMMENDED_GEMINI_MODELS)
        self.assertIn("gemini-2.5-flash", RECOMMENDED_GEMINI_MODELS)
        self.assertIn("gpt-4o-mini", RECOMMENDED_OPENAI_MODELS)
        self.assertIn("float16", RECOMMENDED_COMPUTE_TYPES)
        self.assertIn("int8", RECOMMENDED_COMPUTE_TYPES)


class ManualTests(unittest.TestCase):
    @patch("webbrowser.open")
    def test_manual_opens_readme_html(self, mock_open):
        import manual
        manual.main()
        self.assertTrue(mock_open.called)
        uri = mock_open.call_args[0][0]
        self.assertTrue(uri.startswith("file:///"))


if __name__ == "__main__":
    unittest.main()
