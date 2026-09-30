"""Inspect actual Git-tracked release files without printing secret values."""
import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_PATTERNS = (
    re.compile(rb"AIza[A-Za-z0-9_-]{30,}"),
    re.compile(rb"AQ\.[A-Za-z0-9_-]{35,}"),
    re.compile(rb"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}"),
)
PRIVATE_MARKERS = [
    ("-----BEGIN " + kind + " PRIVATE KEY-----").encode()
    for kind in ("RSA", "EC", "OPENSSH")
] + [("-----BEGIN " + "PRIVATE KEY-----").encode()]


def tracked_files(root=ROOT):
    result = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root,
                            check=True, capture_output=True)
    return sorted(set(result.stdout.decode("utf-8").split("\0")) - {""})


def inspect_files(root, names):
    issues = []
    for name in names:
        path = Path(name)
        leaf = path.name.lower()
        forbidden = (leaf in {"config.json", "gui_settings.json", "key.json", ".env"}
                     or (leaf.startswith(".env.") and leaf != ".env.example")
                     or leaf.endswith((".pem", ".key", ".log", ".pyc"))
                     or any(part in {".git", ".venv", "__pycache__", "dist", "build"}
                            or part.startswith(".autosub_") for part in path.parts)
                     or (leaf.endswith(".json") and ("credential" in leaf or leaf.startswith(("project-", "service-account")))))
        if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v", ".webm", ".ts", ".wav", ".srt"}:
            forbidden = name not in {"examples/hello.en.srt", "examples/demo.en.wav"}
        if path.is_absolute() or ".." in path.parts or forbidden:
            issues.append((name, "private/generated file"))
            continue
        target = root / path
        if target.is_symlink() or not target.is_file():
            issues.append((name, "missing file or symbolic link"))
            continue
        data = target.read_bytes()
        if any(marker in data for marker in PRIVATE_MARKERS) or any(pattern.search(data) for pattern in KEY_PATTERNS):
            issues.append((name, "secret marker"))
        if leaf.endswith((".json", ".example")):
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict):
                if value.get("type") == "service_account" or value.get("private_key"):
                    issues.append((name, "service account data"))
                if any(value.get(key) for key in ("api_key", "credentials", "project", "bucket")):
                    issues.append((name, "personal configuration"))
    return issues


def audit(root=ROOT):
    names = tracked_files(root)
    if not names:
        raise RuntimeError("No Git-tracked files. Stage the reviewed source before building a release.")
    issues = inspect_files(root, names)
    if issues:
        for name, reason in issues:
            print(f"BLOCKED: {name}: {reason}")
        raise RuntimeError("Release file audit failed; secret values are not printed.")
    print(f"Release audit passed: {len(names)} tracked files")
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    audit(args.root.resolve())


if __name__ == "__main__":
    main()
