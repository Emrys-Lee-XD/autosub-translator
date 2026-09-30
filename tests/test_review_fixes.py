"""Regression checks for config precedence and multilingual recovery."""
import contextlib
import io
import json
import os
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
from language_config import source_path, stt_identity, translation_identity
from tests.test_multilang import options, SRT
from srt_utils import read_srt


class ReviewRegressionTests(unittest.TestCase):
    def test_json_numbers_and_languages_outside_gui_presets_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({"batch": 7, "sleep": 0.5,
                                           "source_language": "pt-BR", "target_language": "nl"}), encoding="utf-8")
            values = gui_support.load_settings(config)
            self.assertEqual(values["batch"], "7")
            self.assertEqual(values["sleep"], "0.5")
            source = Path(tmp) / "sample.srt"
            source.write_text(SRT, encoding="utf-8")
            values["input"] = str(source)
            command, _ = gui_support.build_command(values, dry_run=True)
            self.assertIn("--source_language=pt-BR", command)
            self.assertIn("--target_language=nl", command)

    def test_gui_unsaved_reuse_and_empty_prompt_override_disk_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.mp4"
            source.write_bytes(b"video")
            config = Path(tmp) / "config.json"
            gui_support.save_settings({**gui_support.DEFAULTS, "existing": "force",
                                       "keep_workspace": True, "initial_prompt": "old prompt"}, config)
            command, env = gui_support.build_command({"input": str(source)}, dry_run=True)
            with patch.object(sys, "argv", ["main.py", *command[3:], "--config", str(config)]), \
                 patch.dict(os.environ, env, clear=True), patch.object(main, "run_batch", return_value=0) as run, \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                main.main()
            self.assertEqual(stopped.exception.code, 0)
            args = run.call_args.args[1]
            self.assertFalse(args.force)
            self.assertFalse(args.keep_workspace)
            self.assertEqual(args.initial_prompt, "")

    def test_retry_no_text_does_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"video")
            source_path(video, "en").write_text("", encoding="utf-8")
            state = Path(tmp) / "state.json"
            main.update_progress(state, video, status="no_text", video_identity=main.video_identity(video),
                                 stt_identity=stt_identity(options()))
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                code = pipeline.process_input(video, options(retry_no_text=True, dry_run=True),
                                              ROOT, state, None, Path(tmp) / "checkpoints")
            self.assertEqual(code, 0)
            self.assertIn("Step 2/4", log.getvalue())

    def test_translation_failure_resumes_without_repeating_stt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"video")
            state = Path(tmp) / "state.json"
            calls = []

            def fake_run(cmd, **_):
                calls.append(cmd[1])
                if cmd[1] == "ffmpeg_only.py":
                    (Path(cmd[cmd.index("--out_dir") + 1]) / "sample.stt.wav").write_bytes(b"wav")
                elif cmd[1] == "sub.py":
                    Path(cmd[cmd.index("--out") + 1]).write_text(SRT, encoding="utf-8")
                elif calls.count("gemini.py") == 1:
                    raise RuntimeError("temporary translation failure")
                else:
                    gemini.write_translated_srt(cmd[cmd.index("--out") + 1],
                        read_srt(cmd[cmd.index("--in") + 1]), ["translated"], "en", "zh-CN", "bilingual")

            with patch.object(pipeline.core, "run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.process_input(video, options(), ROOT, state, None, Path(tmp) / "checkpoints"), 1)
                self.assertEqual(pipeline.process_input(video, options(), ROOT, state, None, Path(tmp) / "checkpoints"), 0)
            self.assertEqual(calls, ["ffmpeg_only.py", "sub.py", "gemini.py", "gemini.py"])

    def test_force_ignores_cached_translation_and_old_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            source = Path(tmp) / "sample.srt"
            source.write_text(SRT, encoding="utf-8")
            state = Path(tmp) / "state.json"
            checkpoints = Path(tmp) / "checkpoints"
            calls = []

            def fake_run(cmd, **_):
                calls.append(cmd)
                self.assertFalse(Path(cmd[cmd.index("--checkpoint") + 1]).exists())
                gemini.write_translated_srt(cmd[cmd.index("--out") + 1], read_srt(source),
                    ["fresh translation"], "en", "zh-CN", cmd[cmd.index("--output_mode") + 1])

            with patch.object(pipeline.core, "run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.process_input(source, options(), ROOT, state, None, checkpoints), 0)
                key = translation_identity(options(), pipeline.file_sha256(source))
                checkpoints.mkdir(exist_ok=True)
                checkpoint = checkpoints / f"{main.path_fingerprint(source)}.{key[:24]}.part.json"
                checkpoint.write_text('{"old":true}', encoding="utf-8")
                self.assertEqual(pipeline.process_input(source, options(force=True, output_mode="translated"),
                                                       ROOT, state, None, checkpoints), 0)
            self.assertEqual(len(calls), 2)

    def test_missing_stt_output_is_a_failure_not_no_text(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"}):
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"video")
            state = Path(tmp) / "state.json"
            with patch.object(pipeline.core, "run"), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.process_input(video, options(), ROOT, state, None, Path(tmp) / "checkpoints"), 1)
            self.assertEqual(main.load_state(state)[str(video.resolve())]["status"], "failed")

    def test_empty_srt_is_rejected_before_creating_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "empty.srt"
            source.write_text("", encoding="utf-8")
            with patch.object(pipeline.core, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.process_input(source, options(), ROOT, Path(tmp) / "state.json",
                                                       None, Path(tmp) / "checkpoints"), 1)
                run.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [source])


if __name__ == "__main__":
    unittest.main()
