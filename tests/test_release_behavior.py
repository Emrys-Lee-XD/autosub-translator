"""Public release guarantees: state without logs, visible outputs and clean files."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import main
import pipeline
import gemini
from release_audit import inspect_files
from srt_utils import read_srt


class PublicReleaseTests(unittest.TestCase):
    def test_installed_whisper_can_decode_public_wave_sample(self):
        from faster_whisper.audio import decode_audio
        audio = decode_audio(str(ROOT / "examples" / "demo.en.wav"))
        self.assertGreater(len(audio), 16000)

    def test_no_log_keeps_state_and_reuses_visible_output(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            source = Path(tmp) / "source.srt"
            source.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello world\n", encoding="utf-8")
            calls = []
            def fake_run(cmd, **_):
                calls.append(cmd)
                gemini.write_translated_srt(cmd[cmd.index("--out") + 1], read_srt(source),
                                           ["translated"], "en", "zh-CN", "bilingual")
            arguments = ["main.py", str(source), "--no_config", "--source_language", "en", "--no_progress_log"]
            with patch.object(sys, "argv", arguments), patch.object(pipeline.core, "run", side_effect=fake_run), \
                 contextlib.redirect_stdout(io.StringIO()):
                for _ in range(2):
                    with self.assertRaises(SystemExit) as stopped:
                        main.main()
                    self.assertEqual(stopped.exception.code, 0)
            self.assertEqual(len(calls), 1)
            self.assertTrue((Path(tmp) / ".autosub_state.json").exists())
            self.assertFalse((Path(tmp) / ".autosub_progress.jsonl").exists())
            if os.name == "nt":
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(Path(tmp) / "source.zh-CN.bilingual.srt"))
                self.assertNotEqual(attrs, -1)
                self.assertFalse(attrs & 2)

    def test_audit_rejects_private_file_even_if_force_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.json").write_text('{}', encoding="utf-8")
            self.assertTrue(inspect_files(root, ["config.json"]))

    def test_audit_rejects_key_in_an_allowed_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("AI" + "za" + "x" * 35, encoding="utf-8")
            self.assertTrue(inspect_files(root, ["README.md"]))


if __name__ == "__main__":
    unittest.main()
