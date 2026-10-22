"""Batch state has exactly one owner: the scheduler's calling thread."""
import threading
from pathlib import Path

import main as core


class StateStore:
    def __init__(self, path, log_path=None):
        self.path = path
        self.log_path = log_path
        self.owner = threading.get_ident()
        self.records = core.load_state(path) if path else {}

    def get(self, source):
        item = self.records.get(str(Path(source).resolve()), {})
        return dict(item) if isinstance(item, dict) else {}

    def update(self, source, **fields):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Only the scheduler may write task state")
        key = str(Path(source).resolve())
        item = self.get(source)
        item.update(fields)
        item["updated_at"] = core.now_text()
        self.records[key] = item
        if self.path:
            core.save_state(self.path, self.records)
        return item

    def log(self, source, event, **fields):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Only the scheduler may write progress logs")
        try:
            core.append_log(self.log_path, source, event, **fields)
        except OSError as exc:
            core.Log.warn(f"Progress log unavailable: {exc}")
