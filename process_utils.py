"""Owned subprocesses: bounded waits and descendant cleanup on parent exit."""
import ctypes
import json
import os
import signal
import subprocess
import threading
from collections import deque
from ctypes import wintypes
from translation_config import redact


class StageError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class WindowsJob:
    def __init__(self, process):
        self.handle = None
        if os.name != "nt":
            return
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OwnedProcess:
    def __init__(self, command, cwd, *, env=None, stdin=subprocess.DEVNULL,
                 stderr=subprocess.STDOUT):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=stdin,
            stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=flags,
            start_new_session=os.name != "nt")
        try:
            self.job = WindowsJob(self.process)
        except BaseException:
            self.process.kill()
            self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                if pipe:
                    pipe.close()
            raise

    def close(self):
        process = self.process
        # Closing the job kills descendants even when the direct child exited.
        self.job.close()
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe:
                pipe.close()


def run_captured(command, cwd=None, timeout_seconds=None, log=None):
    owned = OwnedProcess(command, cwd)
    tail = deque(maxlen=15)
    error_code = []
    def read():
        for line in owned.process.stdout:
            line = redact(line.rstrip())
            if line.startswith("__AUTOSUB_TRANSLATION_ERROR__"):
                try:
                    error_code.append(json.loads(line.split("__AUTOSUB_TRANSLATION_ERROR__", 1)[1]).get("code"))
                except ValueError:
                    pass
            else:
                tail.append(line)
                if log:
                    log(line)
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    try:
        try:
            code = owned.process.wait(timeout=timeout_seconds or None)
        except subprocess.TimeoutExpired as exc:
            raise StageError(f"Stage timed out after {timeout_seconds}s", code="timeout") from exc
        thread.join(timeout=5)
        if code:
            message = "\n".join(tail) or f"Subprocess failed ({code})"
            disk_full = any(part in message.lower() for part in
                            ("no space left on device", "not enough space on the disk", "disk full"))
            raise StageError(message, code="disk_full" if disk_full else error_code[-1] if error_code else None)
    finally:
        owned.close()
        thread.join(timeout=5)
