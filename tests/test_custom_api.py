"""Exercise provider configuration and real HTTP requests without external APIs."""
import contextlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gui_support
import translate
import translation_core
from language_config import translation_identity
from model_config import DEFAULT_MODEL
from srt_utils import read_srt
from tests.test_multilang import options, SRT
from translation_config import TranslationConfig, credential_environment, normalize_base_url, redact
from translation_core import ResponseFormatError, retry_after_seconds, retry_translation
from translation_providers import OpenAICompatibleProvider, ProviderError


class LocalAPI:
    def __init__(self, responder=None):
        self.requests = []
        self.responder = responder

    def __enter__(self):
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.0 closes immediately after the response; on Windows that can
            # reset an httpx connection before the response body is consumed.
            protocol_version = "HTTP/1.1"

            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError:
                    pass  # Clients may close their idle keep-alive connection.

            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.requests.append((self.path, dict(self.headers), body))
                lines = json.loads(body["messages"][0]["content"].split("待翻译 JSON 数组：\n", 1)[1])
                if fixture.responder:
                    status, result, headers, delay = fixture.responder(body, lines, len(fixture.requests))
                else:
                    texts = ["译文 " + text for text in lines]
                    value = {"translations": texts} if "response_format" in body else texts
                    status, result, headers, delay = 200, completion(value), {}, 0
                if delay:
                    time.sleep(delay)
                payload = json.dumps(result).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(payload)
                except ConnectionError:
                    pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/gateway/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.env_patch = patch.dict(os.environ, {"NO_PROXY": "127.0.0.1,localhost"})
        self.env_patch.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.env_patch.stop()

    def config(self, **overrides):
        return TranslationConfig.from_values(dict(translation_provider="openai_compatible", model="local-model",
                                                  api_base_url=self.url, **overrides))


def completion(value):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value, ensure_ascii=False)}}]}


class ProviderConfigurationTests(unittest.TestCase):
    def test_endpoint_normalization_and_invalid_urls(self):
        self.assertEqual(normalize_base_url(" HTTPS://Example.COM:443/api/v1/ "), "https://example.com/api/v1")
        self.assertEqual(normalize_base_url("http://[::1]:8080/v1"), "http://[::1]:8080/v1")
        for url in ("", "ftp://example.com", "https://user:pass@example.com", "https://example.com?key=x",
                    "https://example.com/#x", "https://example.com/v1/chat/completions", "https://bad host", "https://x:bad",
                    "http://example.com:0/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_base_url(url)

    def test_cache_separates_endpoints_protocols_and_vertex_projects(self):
        custom = dict(translation_provider="openai_compatible", api_base_url="https://example.com/v1", model="same-model")
        first = translation_identity(options(**custom), "source")
        for change in ({"api_base_url": "https://other.example/v1"}, {"api_base_url": "https://example.com/other"},
                       {"response_format": "json_object"}, {"model": "another"}):
            self.assertNotEqual(first, translation_identity(options(**{**custom, **change}), "source"))
        self.assertEqual(first, translation_identity(options(**{**custom, "api_base_url": "https://example.com/v1/",
                                                               "custom_api_key_env": "ANOTHER_KEY"}), "source"))
        self.assertNotEqual(first, translation_identity(options(model="same-model"), "source"))
        vertex = dict(gemini_backend="vertex", model="same-model", project="one")
        self.assertNotEqual(translation_identity(options(**vertex), "source"),
                            translation_identity(options(**{**vertex, "project": "two"}), "source"))
        self.assertNotEqual(translation_identity(options(**vertex), "source"),
                            translation_identity(options(**{**vertex, "location": "us-central1"}), "source"))

    def test_custom_credential_is_independent_and_has_documented_precedence(self):
        cfg = TranslationConfig.from_values(dict(translation_provider="openai_compatible", model="test", api_base_url="https://example.com"))
        saved = {"api_key": "gemini-saved", "custom_api_key": "custom-saved"}
        inherited = {"GEMINI_API_KEY": "gemini-env", "AUTOSUB_API_KEY": "custom-env"}
        self.assertEqual(cfg.api_key(credential_environment(cfg, saved, inherited)), "custom-env")
        self.assertEqual(cfg.api_key(credential_environment(cfg, saved, inherited, override=True)), "custom-saved")
        self.assertEqual(cfg.api_key({"GEMINI_API_KEY": "gemini-env"}), "")
        env = credential_environment(TranslationConfig(), saved, inherited)
        self.assertEqual(env["GEMINI_API_KEY"], "gemini-env")
        cfg = TranslationConfig.from_values(dict(translation_provider="openai_compatible", model="test",
                                                 api_base_url="https://example.com", custom_api_key_env="VENDOR_TOKEN"))
        env = credential_environment(cfg, {"custom_api_key": "vendor-secret"}, {})
        self.assertEqual(redact("echo vendor-secret", env), "echo [REDACTED]")

    def test_old_settings_migrate_only_for_gemini_and_new_fields_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"model": "gemini-3.1-flash-lite", "api_key": "old-secret"}))
            values = gui_support.load_settings(path)
            self.assertEqual(values["translation_provider"], "gemini")
            self.assertEqual(values["model"], DEFAULT_MODEL)
            self.assertEqual(values["api_key"], "old-secret")
            path.write_text(json.dumps({"translation_provider": "openai_compatible", "model": "gemini-3.1-flash-lite",
                                        "api_base_url": "https://example.com/v1", "custom_api_key": "custom-secret"}))
            values = gui_support.load_settings(path)
            self.assertEqual(values["model"], "gemini-3.1-flash-lite")
            gui_support.save_settings(values, path)
            self.assertEqual(gui_support.load_settings(path), values)
            path.write_text(json.dumps({"translation_provider": "typo"}))
            with self.assertRaises(ValueError):
                gui_support.load_settings(path)

    def test_retry_after_supports_dates_and_is_bounded(self):
        self.assertEqual(retry_after_seconds("999"), 60)
        self.assertEqual(retry_after_seconds("-1"), 0)
        self.assertIsNone(retry_after_seconds("NaN"))
        date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
        self.assertTrue(18 <= retry_after_seconds(date) <= 20)

    def test_release_audit_rejects_saved_custom_key(self):
        from scripts.release_audit import inspect_files
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json.example"
            path.write_text(json.dumps({"custom_api_key": "synthetic-private-value"}))
            self.assertTrue(inspect_files(Path(tmp), [path.name]))


class HTTPProviderTests(unittest.TestCase):
    def test_gemini_sdk_serializes_native_request_and_parses_response(self):
        import httpx
        from google import genai
        from google.genai import types
        from translation_providers import GeminiProvider
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {
                "role": "model", "parts": [{"text": '["你好"]'}]}, "finishReason": "STOP"}]})
        client = genai.Client(vertexai=False, api_key="synthetic-gemini-key", http_options=types.HttpOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handle))))
        provider = GeminiProvider(TranslationConfig(), client=client)
        try:
            self.assertEqual(provider.translate_lines(["Hello"], "en", "zh-CN"), ["你好"])
            self.assertEqual(len(requests), 1)
            self.assertIn(DEFAULT_MODEL + ":generateContent", requests[0].url.path)
            self.assertEqual(requests[0].headers["x-goog-api-key"], "synthetic-gemini-key")
            body = json.loads(requests[0].content)
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            thinking = body["generationConfig"]["thinkingConfig"]
            self.assertEqual(thinking.get("thinkingLevel", thinking.get("thinking_level")), "LOW")
        finally:
            provider.close()

    def request(self, api, *, response_format="text", timeout=2, attempts=1):
        provider = OpenAICompatibleProvider(api.config(response_format=response_format), timeout=timeout)
        try:
            return retry_translation(lambda: provider.translate_lines(["Hello", "World"], "en", "zh-CN"), attempts, 0)
        finally:
            provider.close()

    def test_all_response_modes_authentication_and_base_path(self):
        with LocalAPI() as api, patch.dict(os.environ, {"AUTOSUB_API_KEY": "custom-secret", "GEMINI_API_KEY": "gemini-secret"}):
            for mode in ("text", "json_object", "json_schema"):
                self.assertEqual(self.request(api, response_format=mode), ["译文 Hello", "译文 World"])
                path, headers, body = api.requests[-1]
                self.assertEqual(path, "/gateway/v1/chat/completions")
                self.assertEqual(headers["Authorization"], "Bearer custom-secret")
                self.assertNotIn("gemini-secret", json.dumps((headers, body)))
                self.assertEqual(body["model"], "local-model")
                self.assertNotIn("thinking_config", body)
                if mode == "text":
                    self.assertNotIn("response_format", body)
                else:
                    self.assertEqual(body["response_format"]["type"], mode)

    def test_no_auth_local_server_never_receives_gemini_key(self):
        with LocalAPI() as api, patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-secret", "AUTOSUB_API_KEY": ""}):
            self.request(api)
            self.assertNotIn("Authorization", api.requests[0][1])

    def test_error_redacts_configured_custom_environment_key(self):
        with LocalAPI(lambda *_: (401, {"error": {"message": "echo vendor-secret"}}, {}, 0)) as api, \
             patch.dict(os.environ, {"VENDOR_TOKEN": "vendor-secret"}):
            provider = OpenAICompatibleProvider(api.config(custom_api_key_env="VENDOR_TOKEN"))
            try:
                with self.assertRaises(ProviderError) as caught:
                    provider.translate_lines(["Hello"])
                self.assertNotIn("vendor-secret", str(caught.exception))
            finally:
                provider.close()

    def test_rate_limit_retries_using_retry_after(self):
        def respond(body, lines, count):
            if count == 1:
                return 429, {"error": {"message": "rate limit"}}, {"Retry-After": "2"}, 0
            return 200, completion(["甲", "乙"]), {}, 0
        with LocalAPI(respond) as api, patch("translation_core.time.sleep") as sleep:
            self.assertEqual(self.request(api, attempts=2), ["甲", "乙"])
            sleep.assert_called_once_with(2)
            self.assertEqual(len(api.requests), 2)

    def test_auth_and_model_errors_are_not_retried_and_keys_are_redacted(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                def respond(*_):
                    return status, {"error": {"message": "bad custom-secret"}}, {}, 0
                with LocalAPI(respond) as api, patch.dict(os.environ, {"AUTOSUB_API_KEY": "custom-secret"}):
                    with self.assertRaises(ProviderError) as caught:
                        self.request(api, attempts=3)
                    self.assertEqual(len(api.requests), 1)
                    self.assertNotIn("custom-secret", str(caught.exception))

    def test_server_error_is_retried(self):
        def respond(body, lines, count):
            return (503, {}, {}, 0) if count == 1 else (200, completion(["甲", "乙"]), {}, 0)
        with LocalAPI(respond) as api:
            self.assertEqual(self.request(api, attempts=2), ["甲", "乙"])
            self.assertEqual(len(api.requests), 2)

    def test_server_error_retries_with_non_utf8_library_log_stream(self):
        def respond(body, lines, count):
            return (503, {}, {}, 0) if count == 1 else (200, completion(["甲", "乙"]), {}, 0)
        with LocalAPI(respond) as api:
            buffer = io.BytesIO()
            with io.TextIOWrapper(buffer, encoding="cp1252") as stream:
                with contextlib.redirect_stdout(stream):
                    result = self.request(api, attempts=2)
                stream.flush()
                self.assertIn(b"503", buffer.getvalue())
            self.assertEqual(result, ["甲", "乙"])
            self.assertEqual(len(api.requests), 2)

    def test_network_timeout_fails_after_bounded_attempts(self):
        def respond(*_):
            return 200, completion(["甲", "乙"]), {}, 0.15
        with LocalAPI(respond) as api:
            with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
                self.request(api, timeout=0.03, attempts=2)
            self.assertEqual(len(api.requests), 2)

    def test_malformed_missing_empty_and_truncated_responses_fail(self):
        for payload in (completion(["only-one"]), completion(["", "乙"]), completion({"wrong": ["甲", "乙"]}),
                        {"choices": []}, {"choices": [{"message": {"content": "not JSON"}}]},
                        {"choices": [{"finish_reason": "length", "message": {"content": '["甲","乙"]'}}]}):
            with self.subTest(payload=payload):
                with LocalAPI(lambda *_: (200, payload, {}, 0)) as api:
                    with self.assertRaises(ResponseFormatError):
                        self.request(api)


class TranslationWorkflowTests(unittest.TestCase):
    def command(self, api, source, *extra):
        return [sys.executable, str(ROOT / "main.py"), str(source), "--no_config",
                "--translation_provider", "openai_compatible", "--api_base_url", api.url,
                "--model", "local-model", "--source_language", "en", "--sleep", "0", *extra]

    def test_cli_translation_reuse_and_endpoint_change(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as first, LocalAPI() as second:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            for api in (first, first, second):
                run = subprocess.run(self.command(api, source), cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(len(first.requests), 1)
            self.assertEqual(len(second.requests), 1)
            output = source.with_name("source.zh-CN.bilingual.srt")
            self.assertEqual(read_srt(output)[0][3], "Hello world\n译文 Hello world")
            self.assertEqual(len(list(Path(tmp).glob("*.backup.*.srt"))), 1)

    def test_real_checkpoint_survives_failure_and_resumes(self):
        fail_second = True
        def respond(body, lines, count):
            if fail_second and count == 2:
                return 503, {"error": {"message": "temporary failure"}}, {}, 0
            return 200, completion(["译文 " + line for line in lines]), {}, 0
        with tempfile.TemporaryDirectory() as tmp, LocalAPI(respond) as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT + "\n2\n00:00:02,000 --> 00:00:03,000\nSecond line\n", encoding="utf-8")
            out = Path(tmp) / "out.srt"
            checkpoint = Path(tmp) / "part.json"
            argv = ["--in", str(source), "--out", str(out), "--checkpoint", str(checkpoint),
                    "--translation_provider", "openai_compatible", "--api_base_url", api.url,
                    "--model", "local-model", "--source_language", "en", "--batch", "1",
                    "--line_retries", "1", "--sleep", "0"]
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                translate.main(argv)
            self.assertFalse(out.exists())
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(data["translations"], ["译文 Hello world"])
            args = options(translation_provider="openai_compatible", api_base_url=api.url, model="local-model")
            self.assertEqual(data["translation_key"], translation_identity(args, translation_core.source_sha256(source)))
            fail_second = False
            with contextlib.redirect_stdout(io.StringIO()):
                translate.main(argv)
            self.assertEqual(len(api.requests), 3)
            self.assertEqual(len(read_srt(out)), 2)
            self.assertFalse(checkpoint.exists())

    def test_switching_endpoint_reuses_video_transcription(self):
        import pipeline
        real_run = pipeline.core.run
        stages = []
        def run(cmd, **kwargs):
            stages.append(cmd[1])
            if cmd[1] == "ffmpeg_only.py":
                from tests.test_multilang import fixture_audio
                fixture_audio(Path(cmd[cmd.index("--out_dir") + 1]) / "sample.stt.wav")
            elif cmd[1] == "sub.py":
                Path(cmd[cmd.index("--out") + 1]).write_text(SRT, encoding="utf-8")
            else:
                real_run(cmd, **kwargs)
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as first, LocalAPI() as second:
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"synthetic video")
            for api in (first, second):
                args = options(translation_provider="openai_compatible", api_base_url=api.url, model="local-model")
                with patch.object(pipeline.core, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(pipeline.process_input(video, args, ROOT, Path(tmp) / "state.json", None,
                                                           Path(tmp) / "checkpoints"), 0)
            self.assertEqual(stages.count("sub.py"), 1)
            self.assertEqual(stages.count("ffmpeg_only.py"), 1)
            self.assertEqual(stages.count("translate.py"), 2)

    def test_gui_command_uses_current_provider_and_no_key_in_arguments(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            values = dict(input=str(source), translation_provider="openai_compatible", model="local-model",
                          api_base_url=api.url, custom_api_key="custom-secret", api_key="gemini-secret",
                          gemini_backend="vertex", credentials="missing.json")
            cmd, env = gui_support.build_command(values)
            self.assertNotIn("--project=", cmd)
            self.assertIn("--translation_provider=openai_compatible", cmd)
            self.assertNotIn("custom-secret", " ".join(cmd))
            run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(api.requests[0][1]["Authorization"], "Bearer custom-secret")

    def test_cli_saved_custom_key_uses_only_selected_environment_name(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            config = Path(tmp) / "settings.json"
            gui_support.save_settings({**gui_support.DEFAULTS, "input": str(source),
                "translation_provider": "openai_compatible", "api_base_url": api.url,
                "custom_api_key": "saved-custom-key", "custom_api_key_env": "VENDOR_TOKEN",
                "api_key": "saved-gemini-key", "model": "local-model", "sleep": "0"}, config)
            env = {**os.environ, "VENDOR_TOKEN": "", "GEMINI_API_KEY": "inherited-gemini-key"}
            run = subprocess.run([sys.executable, str(ROOT / "main.py"), "--config", str(config)],
                                 cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(api.requests[0][1]["Authorization"], "Bearer saved-custom-key")
            self.assertNotIn("saved-custom-key", run.stdout + run.stderr)

    def test_batch_format_failure_falls_back_to_individual_lines(self):
        def respond(body, lines, count):
            value = ["wrong-count"] if len(lines) > 1 else ["译文 " + lines[0]]
            return 200, completion(value), {}, 0
        with tempfile.TemporaryDirectory() as tmp, LocalAPI(respond) as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT + "\n2\n00:00:02,000 --> 00:00:03,000\nSecond line\n", encoding="utf-8")
            run = subprocess.run(self.command(api, source, "--retries", "1"), cwd=ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(len(api.requests), 3)
            self.assertEqual(len(read_srt(source.with_name("source.zh-CN.bilingual.srt"))), 2)

    def test_custom_provider_does_not_inherit_gemini_model_default(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            cmd = self.command(api, source)
            index = cmd.index("--model")
            del cmd[index:index + 2]
            run = subprocess.run(cmd + ["--dry_run"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(api.requests, [])

    def test_api_test_button_helper_sends_one_public_request_without_input(self):
        with LocalAPI() as api:
            result = gui_support.test_translation(dict(translation_provider="openai_compatible", model="local-model",
                                                       api_base_url=api.url))
            self.assertIn("API 测试通过", result)
            self.assertEqual(len(api.requests), 1)
            self.assertIn("Hello. This is a subtitle translation test.", api.requests[0][2]["messages"][0]["content"])

    def test_openai_path_runs_without_importing_google_sdk(self):
        script = """import sys
class RejectGoogle:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'google' or fullname.startswith('google.'):
            raise ImportError('Google SDK must not be imported')
sys.meta_path.insert(0, RejectGoogle())
import translate
translate.main(sys.argv[1:])
"""
        with LocalAPI() as api:
            cmd = [sys.executable, "-c", script, "--test_connection", "--translation_provider", "openai_compatible",
                   "--api_base_url", api.url, "--model", "local-model"]
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_cli_translates_with_non_utf8_inherited_console_encoding(self):
        with tempfile.TemporaryDirectory() as tmp, LocalAPI() as api:
            source = Path(tmp) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
            run = subprocess.run(self.command(api, source), cwd=ROOT, env=env,
                                 capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("OpenAI 兼容 API", run.stdout)
            self.assertEqual(len(api.requests), 1)


if __name__ == "__main__":
    unittest.main()
