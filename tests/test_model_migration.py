import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gemini
import gui_support
from model_config import DEFAULT_MODEL


class Gemini38MigrationTests(unittest.TestCase):
    def test_translation_request_uses_supported_38_parameters(self):
        captured = {}
        def generate(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text='["你好"]')
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        self.assertEqual(gemini.gemini_translate_lines(client, DEFAULT_MODEL, ["こんにちは"]), ["你好"])
        config = captured["config"].model_dump(exclude_none=True)
        self.assertEqual(captured["model"], "gemini-3.8-flash")
        self.assertEqual(config["thinking_config"]["thinking_level"], "LOW")
        self.assertNotIn("thinking_budget", config["thinking_config"])
        for removed in ("temperature", "top_p", "top_k", "candidate_count", "frequency_penalty", "presence_penalty"):
            self.assertNotIn(removed, config)
        self.assertEqual(config["response_mime_type"], "application/json")

    def test_old_gui_default_is_upgraded_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            original = {"model": "gemini-3.1-flash-lite", "project": "my-project", "batch": "10"}
            path.write_text(json.dumps(original))
            settings = gui_support.load_settings(path)
            self.assertEqual(settings["model"], DEFAULT_MODEL)
            self.assertEqual(settings["project"], "my-project")
            self.assertEqual(settings["batch"], "10")
            self.assertEqual(json.loads(path.read_text()), original)
            path.write_text(json.dumps({"model": "custom-model"}))
            self.assertEqual(gui_support.load_settings(path)["model"], "custom-model")

    def test_gui_cli_and_batch_launcher_select_38(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "test.mp4"
            source.write_bytes(b"synthetic")
            command, env = gui_support.build_command({"input": str(source)}, True)
            self.assertIn("--model=gemini-3.8-flash", command)
            for cmd in (command, [sys.executable, str(ROOT / "main.py"), str(source), "--project", "test", "--stt_mode", "local", "--dry_run"]):
                result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--model gemini-3.8-flash", result.stdout)
            self.assertNotIn("--model", (ROOT / "autosub.bat").read_text(encoding="utf-8"))

    def test_previous_model_checkpoint_is_not_used_for_38(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            gemini.save_checkpoint(path, ["旧译文"], 1, "same-source", "gemini-3.1-flash-lite")
            self.assertEqual(gemini.load_checkpoint(path, 1, "same-source", DEFAULT_MODEL), [])


if __name__ == "__main__":
    unittest.main()
