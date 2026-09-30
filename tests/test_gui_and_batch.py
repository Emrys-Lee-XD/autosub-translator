import contextlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main
import gemini
import gui_support as support
from batch_lock import directory_lock


class BatchRecoveryTests(unittest.TestCase):
    def test_force_overrides_no_text_state_even_when_subtitle_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "movie.mp4"
            video.write_bytes(b"video")
            (Path(tmp) / ".autosub_state.json").write_text(json.dumps({str(video.resolve()): {
                "status": "no_text", "video_identity": main.video_identity(video)}}))
            result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(video),
                "--project", "test", "--stt_mode", "local", "--force", "--dry_run"],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Step 4/4", result.stdout)

    def test_malformed_video_state_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, video = Path(tmp) / "state.json", Path(tmp) / "movie.mp4"
            state.write_text(json.dumps({str(video.resolve()): "damaged"}))
            main.update_progress(state, video, status="running")
            self.assertEqual(main.load_state(state)[str(video.resolve())]["status"], "running")

    def test_preparation_failure_does_not_abort_remaining_videos(self):
        args = SimpleNamespace(gui_events=True, stop_file=None)
        with patch.object(main, "process_one", side_effect=[PermissionError("locked"), 0]) as process:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = main.run_batch([Path("a.mp4"), Path("b.mp4")], args, ROOT, None, None, ROOT)
        self.assertEqual(result, 1)
        self.assertEqual(process.call_count, 2)
        self.assertIn('"completed": 2', output.getvalue())

    def test_stop_request_finishes_current_video_and_skips_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop = Path(tmp) / "stop"
            args = SimpleNamespace(gui_events=True, stop_file=stop)
            def finish(*_args):
                stop.touch()
                return 0
            with patch.object(main, "process_one", side_effect=finish) as process:
                result = main.run_batch([Path("a.mp4"), Path("b.mp4")], args, ROOT, None, None, ROOT)
            self.assertEqual(result, 130)
            self.assertEqual(process.call_count, 1)

    def test_lock_blocks_other_process_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = "from batch_lock import directory_lock; import sys\nwith directory_lock(sys.argv[1]): print('acquired')"
            command = [sys.executable, "-c", script, tmp]
            with directory_lock(tmp):
                blocked = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            free = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("Another Autosub", blocked.stderr)
            self.assertEqual(free.returncode, 0, free.stderr)

    def test_checkpoint_disk_failure_does_not_trigger_more_api_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / "in.srt", Path(tmp) / "out.srt"
            source.write_text("1\n00:00:00,000 --> 00:00:01,000\na\n\n2\n00:00:02,000 --> 00:00:03,000\nb\n")
            argv = ["gemini.py", "--in", str(source), "--out", str(out), "--backend", "vertex", "--project", "test", "--model", "test"]
            with patch.object(sys, "argv", argv), patch.object(gemini.genai, "Client"), \
                 patch.object(gemini, "translate_with_retries", return_value=["甲", "乙"]) as translate, \
                 patch.object(gemini, "save_checkpoint", side_effect=PermissionError("full")):
                with self.assertRaises(PermissionError):
                    gemini.main()
            translate.assert_called_once()
            self.assertFalse(out.exists())


class GuiSupportTests(unittest.TestCase):
    def test_commands_keep_paths_with_spaces_and_chinese_as_one_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "中文 & test.mp4"
            video.write_bytes(b"video")
            cmd, env = support.build_command({"input": str(video), "device": "cpu", "compute_type": "float16",
                                              "initial_prompt": "--not-an-option"}, True)
            self.assertEqual(cmd[3], str(video.resolve()))
            self.assertIn("--compute_type=int8", cmd)
            self.assertIn("--initial_prompt=--not-an-option", cmd)
            self.assertIn("--dry_run", cmd)
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_bad_settings_are_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ({"sleep": "nan"}, {"batch": "0"}, {"retries": "1.5"},
                        {"stt_mode": "cloud", "bucket": ""},
                        {"stt_mode": "cloud", "bucket": "test", "project": ""},
                        {"gemini_backend": "vertex", "project": ""},
                        {"stt_mode": "cloud", "bucket": "test", "project": "test", "source_language": "ja",
                         "credentials": str(Path(tmp) / "missing.json")}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    support.build_command({"input": tmp, **bad})
        with self.assertRaises(ValueError):
            support.build_command({"input": ""})

    def test_settings_ignore_unknown_keys_and_bad_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"project": "mine", "stt_mode": "bad", "batch": None, "secret": "ignored"}))
            values = support.load_settings(path)
            self.assertEqual(values["project"], "mine")
            self.assertEqual(values["stt_mode"], "local")
            self.assertEqual(values["batch"], "20")
            support.save_settings(values, path)
            self.assertNotIn("secret", path.read_text())
            self.assertEqual(support.load_settings(path), values)

    def test_pythonw_runner_uses_console_python_for_captured_logs(self):
        with patch.object(support.sys, "executable", "C:/Python/pythonw.exe"):
            self.assertEqual(Path(support.python_executable()).name, "python.exe")

    def test_runner_real_dry_run_reports_completion_without_input_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "测试 video.mp4"
            video.write_bytes(b"video")
            runner = support.ProcessRunner()
            cmd, env = support.build_command({"input": str(video)}, True)
            runner.start(cmd, env)
            events = []
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                item = runner.events.get(timeout=10)
                events.append(item)
                if item[0] == "exit":
                    break
            self.assertEqual(events[-1], ("exit", 0))
            self.assertTrue(any(kind == "progress" and value["event"] == "batch_done" for kind, value in events))
            self.assertEqual(list(Path(tmp).iterdir()), [video])
            self.assertFalse(runner.running)
            self.assertFalse(runner._stop_file.exists())

    def test_runner_spawn_failure_returns_failure_and_reenables(self):
        runner = support.ProcessRunner()
        with patch.object(support.subprocess, "Popen", side_effect=FileNotFoundError("missing")):
            runner.start(["missing"], os.environ.copy())
            runner._thread.join(timeout=5)
        items = []
        while not runner.events.empty():
            items.append(runner.events.get_nowait())
        self.assertIn(("exit", 1), items)
        self.assertFalse(runner.running)


if __name__ == "__main__":
    unittest.main()
