"""Exercise the actual Tk event loop with an isolated dry-run input."""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gui import AutosubApp
from tests.test_custom_api import LocalAPI
from model_config import DEFAULT_MODEL


class GuiSmokeTests(unittest.TestCase):
    def test_provider_switch_keeps_separate_keys_and_models_and_loads_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tk.Tk()
            root.withdraw()
            app = AutosubApp(root, settings_path=Path(tmp) / "settings.json")
            try:
                app.vars["api_key"].set("gemini-secret")
                app.vars["translation_provider"].set("openai_compatible")
                app._mode_changed()
                self.assertEqual(app.vars["model"].get(), "")
                self.assertTrue(app.fields["api_key"].instate(["disabled"]))
                self.assertTrue(app.fields["api_base_url"].instate(["!disabled"]))
                app.vars["custom_api_key"].set("custom-secret")
                app.vars["api_base_url"].set("http://localhost:1234/v1")
                app.vars["model"].set("local-model")
                app.save()
                app.vars["translation_provider"].set("gemini")
                app._mode_changed()
                self.assertEqual(app.vars["model"].get(), DEFAULT_MODEL)
                self.assertEqual(app.vars["api_key"].get(), "gemini-secret")
                self.assertTrue(app.fields["custom_api_key"].instate(["disabled"]))
                app.load()
                self.assertEqual(app.vars["translation_provider"].get(), "openai_compatible")
                self.assertEqual(app.vars["model"].get(), "local-model")
                self.assertEqual(app.vars["custom_api_key"].get(), "custom-secret")
            finally:
                root.destroy()

    def test_api_button_completes_in_real_tk_event_loop(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            root = tk.Tk()
            root.withdraw()
            app = AutosubApp(root, settings_path=Path(tmp) / "settings.json")
            try:
                app.vars["translation_provider"].set("openai_compatible")
                app._mode_changed()
                app.vars["api_base_url"].set(api.url)
                app.vars["model"].set("local-model")
                app.test_api()
                self.assertTrue(app.checking)
                deadline = time.monotonic() + 10
                while app.checking and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.02)
                self.assertFalse(app.checking)
                self.assertIn("API 测试通过", app.status.get())
                self.assertEqual(len(api.requests), 1)
            finally:
                root.destroy()

    def test_turbo_config_cloud_switch_and_structured_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tk.Tk()
            root.withdraw()
            try:
                app = AutosubApp(root, settings_path=Path(tmp) / "config.json")
                app.vars["turbo"].set(True)
                app.vars["audio_prefetch"].set("3")
                app._mode_changed()
                self.assertEqual(app.stop_button.cget("text"), "安全停止")
                app.save()
                app.vars["turbo"].set(False)
                app.load()
                self.assertTrue(app.vars["turbo"].get())
                self.assertEqual(app.vars["audio_prefetch"].get(), "3")
                app.vars["stt_mode"].set("cloud")
                app._mode_changed()
                self.assertFalse(app.vars["turbo"].get())
                self.assertTrue(app.turbo_check.instate(["disabled"]))
                app._progress(dict(event="batch_start", turbo=True, total=5))
                app._progress(dict(event="turbo_status", total=5, completed=1, failed=0,
                    finished=1, no_text=0, recognized=3, pending_translation=1, model="resident",
                    stages=dict(extract="2.mp4", stt="3.mp4", translate="1.mp4")))
                self.assertEqual(app.stage_vars["extract"].get(), "2.mp4")
                self.assertEqual(app.stage_vars["stt"].get(), "3.mp4")
                self.assertEqual(app.stage_vars["translate"].get(), "1.mp4")
                self.assertIn("待翻译 1", app.counter.get())
                app._progress(dict(event="turbo_stt_progress", video="3.mp4", seconds=20, duration=60))
                self.assertIn("20 / 60", app.stage_vars["stt"].get())
            finally:
                root.destroy()

    def test_gui_saves_and_reloads_api_key_and_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            root = tk.Tk()
            root.withdraw()
            try:
                app = AutosubApp(root, settings_path=path)
                app.vars["api_key"].set("test-secret")
                app.vars["source_language"].set("ja")
                app.save()
                app.vars["api_key"].set("")
                app.vars["source_language"].set("en")
                app.load()
                self.assertEqual(app.vars["api_key"].get(), "test-secret")
                self.assertEqual(app.vars["source_language"].get(), "ja")
                self.assertEqual(app.fields["source_language"].get(), "日语")
                app.vars["target_language"].set("pt-BR")
                app.save()
                app.vars["target_language"].set("en")
                app.load()
                self.assertEqual(app.vars["target_language"].get(), "pt-BR")
                self.assertEqual(app.fields["target_language"].get(), "pt-BR")
            finally:
                root.destroy()

    def test_actual_window_dry_run_validation_and_control_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tk.Tk()
            root.withdraw()
            app = AutosubApp(root, settings_path=Path(tmp) / "settings.json")
            try:
                with patch("gui.messagebox.showerror") as error:
                    app.start(True)
                    error.assert_called_once()
                    self.assertFalse(app.busy)
                video = Path(tmp) / "中文 sample.mp4"
                video.write_bytes(b"test")
                app.vars["input"].set(str(video))
                app.start(True)
                self.assertTrue(app.busy)
                self.assertTrue(app.start_button.instate(["disabled"]))
                timeout = time.monotonic() + 15
                while app.busy and time.monotonic() < timeout:
                    root.update()
                    time.sleep(0.02)
                self.assertFalse(app.busy)
                self.assertEqual(app.last_exit, 0)
                self.assertIn("预演完成", app.status.get())
                self.assertTrue(app.start_button.instate(["!disabled"]))
                self.assertTrue(app.stop_button.instate(["disabled"]))
                self.assertIn("1 / 1", app.counter.get())
                self.assertIn("Step 4/4", app.log.get("1.0", "end"))
                self.assertEqual(list(Path(tmp).iterdir()), [video])
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
