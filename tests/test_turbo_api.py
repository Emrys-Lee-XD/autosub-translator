"""Cross-provider integration through real translator subprocesses."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from process_utils import StageError, run_captured
from srt_utils import read_srt
from tests.test_custom_api import LocalAPI, completion
from tests.test_multilang import SRT, fixture_audio, options
from tests.test_turbo import FakeWorker
from turbo_scheduler import TurboScheduler


class TurboAPIIntegrationTests(unittest.TestCase):
    def test_custom_srt_all_response_modes_without_gemini_key_or_model(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            for mode in ("text", "json_object", "json_schema"):
                with self.subTest(mode=mode):
                    source = Path(tmp) / f"{mode}.srt"
                    source.write_text(SRT, encoding="utf-8")
                    env = {k: v for k, v in os.environ.items()
                           if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
                    cmd = [sys.executable, "main.py", str(source), "--no_config", "--turbo",
                           "--translation_provider", "openai_compatible", "--api_base_url", api.url,
                           "--model", "local-model", "--response_format", mode, "--sleep", "0"]
                    run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                                         text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertEqual(len(read_srt(source.with_name(f"{mode}.zh-CN.bilingual.srt"))), 1)
                    metrics = json.loads((Path(tmp) / ".autosub_turbo_metrics.json").read_text())
                    self.assertEqual(metrics["model_initializations"], 0)
            self.assertEqual(len(api.requests), 3)

    def test_real_status_protocol_pauses_translation_but_finishes_stt(self):
        for status in (401, 403, 404, 429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                with LocalAPI(lambda *_: (status, {"error": {"message": "invalid test-token"}}, {}, 0)) as api:
                    folder = Path(tmp)
                    paths = [folder / f"{i}.mp4" for i in range(3)]
                    for path in paths:
                        path.write_bytes(b"synthetic-video")
                    FakeWorker.instances, FakeWorker.calls, FakeWorker.hook = [], [], None
                    def runner(cmd, **kwargs):
                        if cmd[1] == "ffmpeg_only.py":
                            fixture_audio(Path(cmd[cmd.index("--out_dir") + 1]) / f"{Path(cmd[2]).stem}.stt.wav")
                        else:
                            run_captured(cmd, **kwargs)
                    args = options(turbo=True, audio_prefetch=2, stop_file=None, retries=1,
                                   translation_provider="openai_compatible", api_base_url=api.url,
                                   custom_api_key_env="VENDOR_TOKEN", request_timeout_seconds=3)
                    env = {"VENDOR_TOKEN": "test-token", "AUTOSUB_ACTIVE_KEY_ENV": "VENDOR_TOKEN"}
                    with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
                        scheduler = TurboScheduler(paths, args, ROOT, folder / "state.json", None,
                                                   folder / "parts", worker_factory=FakeWorker, runner=runner)
                        self.assertEqual(scheduler.run(), 1)
                    self.assertEqual(len(FakeWorker.calls), 3)
                    self.assertEqual(scheduler.loads, 1)
                    self.assertTrue(scheduler.translate_blocked)
                    self.assertEqual(len(api.requests), 1)
                    state = (folder / "state.json").read_text(encoding="utf-8")
                    self.assertNotIn("test-token", state)
                    self.assertIn("[REDACTED]", state)

    def test_key_rotation_reuses_output_and_endpoint_change_retranslates(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as first, LocalAPI() as second:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            for api, key, turbo in ((first, "first-token", True), (first, "new-token", False),
                                    (second, "other-token", True)):
                cmd = [sys.executable, "main.py", str(source), "--no_config",
                       "--turbo" if turbo else "--no_turbo", "--translation_provider", "openai_compatible",
                       "--api_base_url", api.url, "--model", "local-model", "--sleep", "0"]
                run = subprocess.run(cmd, cwd=ROOT, env={**os.environ, "AUTOSUB_API_KEY": key},
                                     capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertNotIn(key, run.stdout + run.stderr)
            self.assertEqual(len(first.requests), 1)
            self.assertEqual(len(second.requests), 1)
            self.assertEqual(first.requests[0][1]["Authorization"], "Bearer first-token")
            self.assertEqual(len(list(Path(tmp).glob("*.backup.*.srt"))), 1)

    def test_legacy_and_shared_entrypoints_emit_same_error_protocol(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI(
                lambda *_: (401, {"error": {"message": "no access"}}, {}, 0)) as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            for entry in ("translate.py", "gemini.py"):
                cmd = [sys.executable, entry, "--in", str(source), "--out", str(Path(tmp) / "out.srt"),
                       "--translation_provider", "openai_compatible", "--api_base_url", api.url,
                       "--model", "local-model", "--line_retries", "1"]
                with self.subTest(entry=entry), self.assertRaises(StageError) as caught:
                    run_captured(cmd, cwd=ROOT, timeout_seconds=10)
                self.assertEqual(caught.exception.code, 401)

    def test_turbo_srt_has_no_google_sdk_import_dependency(self):
        script = """import sys
class RejectGoogle:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'google' or fullname.startswith('google.'):
            raise ImportError('Google SDK must not be imported')
sys.meta_path.insert(0, RejectGoogle())
import main
main.main()
"""
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            cmd = [sys.executable, "-c", script, str(source), "--no_config", "--turbo",
                   "--translation_provider", "openai_compatible", "--api_base_url", api.url,
                   "--model", "local-model", "--sleep", "0"]
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
