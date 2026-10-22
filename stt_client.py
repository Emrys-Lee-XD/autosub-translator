"""Nonblocking controller for the persistent STT child."""
import json
import os
import subprocess
import sys
import threading
import time
import uuid

from process_utils import OwnedProcess, redact


class SttClient:
    def __init__(self, script_dir, config, post):
        self.generation = uuid.uuid4().hex
        self.post = post
        self.intentional = False
        self.started = time.monotonic()
        self.ready = False
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(name, None)
        self.owned = OwnedProcess([sys.executable, "-u", "stt_worker.py"], script_dir,
                                  env=env, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.threads = [threading.Thread(target=self._read_events, daemon=True),
                        threading.Thread(target=self._read_logs, daemon=True)]
        for thread in self.threads:
            thread.start()
        try:
            self.send("initialize", config=config)
        except BaseException:
            self.close(graceful=False)
            raise

    def send(self, command, **fields):
        self.owned.process.stdin.write(json.dumps(dict(protocol=1,
            generation=self.generation, command=command, **fields), ensure_ascii=False) + "\n")
        self.owned.process.stdin.flush()

    def transcribe(self, task):
        self.send("transcribe", job_id=task.job_id, attempt=task.attempt,
                  audio=str(task.wav), output=str(task.source_tmp), config=task.stt_config())

    def _read_events(self):
        try:
            for line in self.owned.process.stdout:
                try:
                    event = json.loads(line)
                    if (not isinstance(event, dict) or event.get("protocol") != 1 or
                            event.get("generation") != self.generation):
                        raise ValueError("Invalid worker event")
                    self.post(dict(kind="stt", **event))
                except (ValueError, TypeError):
                    self.post(dict(kind="stt", event="worker_fatal", generation=self.generation,
                                   error="Malformed worker protocol"))
                    break
        except (OSError, ValueError):
            if not self.intentional:
                self.post(dict(kind="stt", event="worker_fatal", generation=self.generation,
                               error="STT protocol pipe closed unexpectedly"))
        finally:
            if not self.intentional:
                self.post(dict(kind="stt", event="worker_exit", generation=self.generation))

    def _read_logs(self):
        try:
            for line in self.owned.process.stderr:
                self.post(dict(kind="log", stage="stt", text=redact(line.rstrip())))
        except (OSError, ValueError):
            pass  # Pipe closure is reported by the protocol reader.

    def close(self, graceful=True):
        self.intentional = True
        process = self.owned.process
        try:
            if graceful and process.poll() is None:
                self.send("shutdown")
                process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self.owned.close()
            for thread in self.threads:
                thread.join(timeout=5)
