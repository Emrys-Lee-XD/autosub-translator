"""Cross-process nonblocking locks for overlapping output directories."""
import hashlib
import os
import tempfile
from contextlib import contextmanager, ExitStack
from pathlib import Path


@contextmanager
def directory_lock(directory):
    key = hashlib.sha256(os.path.normcase(str(Path(directory).resolve())).encode()).hexdigest()
    lock_root = Path(tempfile.gettempdir()) / "autosub-directory-locks"
    lock_root.mkdir(exist_ok=True)
    with (lock_root / (key + ".lock")).open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another Autosub task is using this directory: {directory}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def batch_locks(directories):
    with ExitStack() as stack:
        for directory in sorted({Path(p).resolve() for p in directories}):
            stack.enter_context(directory_lock(directory))
        yield
