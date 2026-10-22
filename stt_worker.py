"""Persistent Whisper process. stdout is exclusively versioned JSON Lines."""
import contextlib
import json
import os
import queue
import sys
import threading
import time

from stt_engine import load_model, transcribe_one

PROTOCOL = 1


def serve(loader=load_model, transcriber=transcribe_one, commands=None, output=None):
    output = output or sys.stdout
    inbox = commands or queue.Queue(maxsize=2)
    reader = None
    reader_started = False
    if commands is None:
        def read_commands():
            try:
                for line in sys.stdin:
                    inbox.put(json.loads(line))
            finally:
                # The parent died or closed its command pipe: release CUDA even
                # if CTranslate2 is currently busy and cannot consume commands.
                os._exit(2)
        reader = threading.Thread(target=read_commands, daemon=True)
    model = None
    generation = None
    def emit(event, **data):
        print(json.dumps(dict(protocol=PROTOCOL, generation=generation,
                              event=event, **data), ensure_ascii=False), file=output, flush=True)
    try:
        while True:
            # Import/load native libraries before another thread blocks on stdin.
            # On Windows, native DLL initialization can otherwise deadlock.
            command = inbox.get() if commands is not None or reader_started else json.loads(sys.stdin.readline())
            generation = command.get("generation")
            if command.get("protocol") != PROTOCOL:
                raise ValueError("Unsupported STT protocol")
            operation = command.get("command")
            if operation == "shutdown":
                return
            if operation == "initialize":
                if model is not None:
                    raise ValueError("A worker may initialize its model only once")
                started = time.monotonic()
                with contextlib.redirect_stdout(sys.stderr):
                    model = loader(command["config"])
                backend = getattr(model, "model", None)
                emit("worker_ready", load_seconds=time.monotonic() - started,
                     device=str(getattr(backend, "device", command["config"]["device"])),
                     pid=os.getpid())
                if reader:
                    reader.start()
                    reader_started = True
                continue
            if operation != "transcribe" or model is None:
                raise ValueError("Worker is not initialized")
            job = dict(job_id=command["job_id"], attempt=command["attempt"])
            emit("job_started", **job)
            started = time.monotonic()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    summary = transcriber(model, command["audio"], command["output"],
                        command["config"], lambda fields: emit("job_progress", **job, **fields))
                emit("job_completed", **job, seconds=time.monotonic() - started, summary=summary)
            except Exception as exc:
                message = str(exc)
                fatal = any(word in message.lower() for word in
                    ("cuda", "out of memory", "cublas", "cudnn", "device-side"))
                emit("job_failed", **job, error=message, fatal=fatal)
                if fatal:
                    return
    except Exception as exc:
        emit("worker_fatal", error=str(exc))
    finally:
        del model


if __name__ == "__main__":
    serve()
