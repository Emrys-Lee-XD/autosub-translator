"""Behavior checks for the new pipeline, including state and secret handling."""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gemini
import gui_support
import main
import pipeline
import sub
from language_config import source_path, stt_identity
from srt_utils import read_srt


SRT = "1\n00:00:00,000 --> 00:00:01,000\nHello world\n"


def options(**overrides):
    values = dict(source_language="en", target_language="zh-CN", output_mode="bilingual",
                  gemini_backend="developer", model="test-model", stt_mode="local",
                  whisper_model="small", device="cpu", compute_type="int8",
                  hallucination_filter="off", dedupe_window_seconds=0.1, initial_prompt="",
                  force=False, retry_no_text=False, dry_run=False, keep_workspace=False,
                  bucket="", project="", location="global", batch=20, sleep=0,
                  stt_timeout_hours=3, local_stt_timeout_minutes=0,
                  translate_timeout_minutes=10, cloud_language_code="", retries=3)
    values.update(overrides)
    return argparse.Namespace(**values)


class MultilingualTests(unittest.TestCase):
    def test_key_is_saved_in_local_config_but_not_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            values = {"input": str(source), "api_key": "test-secret", "source_language": "en"}
            command, env = gui_support.build_command(values)
            self.assertFalse(any("test-secret" in part for part in command))
            self.assertEqual(env["GEMINI_API_KEY"], "test-secret")
            self.assertFalse(any("--project" in part for part in command))
            path = Path(tmp) / "config.json"
            gui_support.save_settings({**gui_support.DEFAULTS, **values}, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["api_key"], "test-secret")
            self.assertEqual(gui_support.load_settings(path)["api_key"], "test-secret")

    def test_cli_loads_custom_config_and_allows_argument_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            config = Path(tmp) / "config.json"
            gui_support.save_settings({**gui_support.DEFAULTS, "input": str(source),
                                       "model": "custom-model", "source_language": "en",
                                       "target_language": "it", "output_mode": "translated"}, config)
            result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--config", str(config),
                                     "--target_language", "fr", "--dry_run"], cwd=ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("source.fr.translated.srt", result.stdout)
            self.assertIn("--model custom-model", result.stdout)

    def test_bad_json_is_reported_instead_of_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text('{"api_key":', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON"):
                gui_support.load_settings(config)

    def test_english_words_keep_spaces(self):
        words = [{"word": "Hello", "start": 0, "end": 0.4},
                 {"word": "world", "start": 0.5, "end": 0.9},
                 {"word": "!", "start": 0.9, "end": 1.0}]
        self.assertEqual(sub.segment_words(words, 50, 5, 2, "en")[0]["text"], "Hello world!")
        chinese = [{"word": "你好", "start": 0, "end": 0.4},
                   {"word": "世界", "start": 0.5, "end": 0.9}]
        self.assertEqual(sub.segment_words(chinese, 50, 5, 2, "cmn-Hans-CN")[0]["text"], "你好世界")

    def test_developer_client_uses_key_and_needs_no_project(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            source = Path(tmp) / "source.srt"
            output = Path(tmp) / "output.srt"
            source.write_text(SRT, encoding="utf-8")
            args = ["gemini.py", "--in", str(source), "--out", str(output),
                    "--source_language", "en", "--target_language", "it", "--sleep", "0"]
            with patch.object(sys, "argv", args), patch.object(gemini.genai, "Client") as client, \
                 patch.object(gemini, "translate_with_retries", return_value=["Ciao mondo"]):
                gemini.main()
            client.assert_called_once_with(vertexai=False, api_key="test-secret")
            self.assertIn("Ciao mondo", output.read_text(encoding="utf-8"))

    def test_authentication_error_is_not_retried(self):
        error = RuntimeError("invalid API key")
        error.code = 401
        client = type("Client", (), {})()
        with patch.object(gemini, "gemini_translate_lines", side_effect=error) as request:
            with self.assertRaises(RuntimeError):
                gemini.translate_with_retries(client, "model", ["text"], 3, 0)
        request.assert_called_once()

    def test_new_checkpoint_rejects_another_language_and_legacy_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "part.json"
            gemini.save_checkpoint(path, ["Ciao"], 2, "source-hash", "model", "en-to-it")
            self.assertEqual(gemini.load_checkpoint(path, 2, "source-hash", "model", "en-to-it"), ["Ciao"])
            self.assertEqual(gemini.load_checkpoint(path, 2, "source-hash", "model", "en-to-fr"), [])
            gemini.save_checkpoint(path, ["旧译文"], 2, "source-hash", "model")
            self.assertEqual(gemini.load_checkpoint(path, 2, "source-hash", "model", "en-to-it"), [])

    @unittest.skipUnless(os.name == "nt", "Windows batch launcher")
    def test_batch_launcher_uses_local_python_without_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            result = subprocess.run(["cmd", "/c", str(ROOT / "autosub.bat"), str(source),
                                     "--source_language", "en", "--dry_run"],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("source.zh-CN.bilingual.srt", result.stdout)

    def test_srt_outputs_coexist_and_reuse_correct_record(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            root = Path(tmp)
            source = root / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            state = root / "state.json"
            calls = []

            def fake_run(cmd, **_):
                self.assertEqual(cmd[1], "gemini.py")
                self.assertNotIn("test-secret", " ".join(cmd))
                calls.append(cmd)
                original = Path(cmd[cmd.index("--in") + 1])
                output = Path(cmd[cmd.index("--out") + 1])
                target = cmd[cmd.index("--target_language") + 1]
                mode = cmd[cmd.index("--output_mode") + 1]
                gemini.write_translated_srt(output, read_srt(original),
                                            ["你好" if target == "zh-CN" else "Hello"],
                                            "en", target, mode)

            with patch.object(pipeline.core, "run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(pipeline.process_input(source, options(), ROOT, state, None, root / "checkpoints"), 0)
                    self.assertEqual(pipeline.process_input(source, options(target_language="it", output_mode="translated"), ROOT, state, None, root / "checkpoints"), 0)
                    self.assertEqual(pipeline.process_input(source, options(), ROOT, state, None, root / "checkpoints"), 0)
                    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                        self.assertEqual(pipeline.process_input(source, options(output_mode="translated"), ROOT, state, None, root / "checkpoints"), 0)
            self.assertEqual(len(calls), 2)
            self.assertTrue((root / "source.zh-CN.bilingual.srt").exists())
            self.assertTrue((root / "source.it.translated.srt").exists())
            self.assertTrue((root / "source.zh-CN.translated.srt").exists())
            self.assertEqual(len(json.loads(state.read_text(encoding="utf-8"))[str(source.resolve())]["outputs"]), 3)

    def test_unknown_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            root = Path(tmp)
            source = root / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            output = root / "source.zh-CN.bilingual.srt"
            output.write_text("untrusted", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                result = pipeline.process_input(source, options(), ROOT, root / "state.json", None, root / "checkpoints")
            self.assertEqual(result, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "untrusted")

    def test_changed_stt_settings_replace_known_source_after_backup(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            root = Path(tmp)
            video = root / "movie.mp4"
            video.write_bytes(b"synthetic video")
            source = source_path(video, "en")
            source.write_text(SRT.replace("Hello world", "old source"), encoding="utf-8")
            state = root / "state.json"
            old = options(whisper_model="old-model")
            record = {str(video.resolve()): {"video_identity": main.video_identity(video),
                                            "stt_identity": stt_identity(old),
                                            "source_sha256": pipeline.file_sha256(source)}}
            state.write_text(json.dumps(record), encoding="utf-8")

            def fake_run(cmd, **_):
                if cmd[1] == "ffmpeg_only.py":
                    (Path(cmd[cmd.index("--out_dir") + 1]) / "movie.stt.wav").write_bytes(b"wav")
                elif cmd[1] == "sub.py":
                    Path(cmd[cmd.index("--out") + 1]).write_text(SRT, encoding="utf-8")
                else:
                    gemini.write_translated_srt(cmd[cmd.index("--out") + 1], read_srt(source),
                                                ["你好"], "en", "zh-CN", "bilingual")

            with patch.object(pipeline.core, "run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.process_input(video, options(), ROOT, state, None, root / "checkpoints"), 0)
            self.assertIn("Hello world", source.read_text(encoding="utf-8"))
            backups = list(root.glob("movie.source.en.backup.*.srt"))
            self.assertEqual(len(backups), 1)
            self.assertIn("old source", backups[0].read_text(encoding="utf-8"))

    def test_changed_no_text_settings_do_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "movie.mp4"
            video.write_bytes(b"synthetic video")
            source = source_path(video, "en")
            source.write_text("", encoding="utf-8")
            state = root / "state.json"
            state.write_text(json.dumps({str(video.resolve()): {
                "status": "no_text", "video_identity": main.video_identity(video),
                "stt_identity": stt_identity(options(whisper_model="old-model"))}}), encoding="utf-8")
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                result = pipeline.process_input(video, options(dry_run=True), ROOT, state, None, root / "checkpoints")
            self.assertEqual(result, 0)
            self.assertIn("Step 2/4", log.getvalue())
            self.assertEqual(source.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
