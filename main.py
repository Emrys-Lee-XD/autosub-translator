#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import hashlib
import math
from srt_utils import read_srt
import json
import re
import shutil
import subprocess
import sys
import os
import time
import uuid
from pathlib import Path
from typing import Optional, List
from contextlib import nullcontext
from batch_lock import batch_locks
from model_config import DEFAULT_MODEL, DEFAULT_LOCATION
from language_config import language_tag, output_path, source_path, SPEECH_CODES
from version import __version__

class Log:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"

    @staticmethod
    def step(msg): print(f"\n{Log.BOLD}{Log.CYAN}>> {msg}{Log.RESET}")
    @staticmethod
    def info(msg): print(f"   {msg}")
    @staticmethod
    def success(msg): print(f"{Log.GREEN}   [OK] {msg}{Log.RESET}")
    @staticmethod
    def warn(msg): print(f"{Log.YELLOW}   [WARN] {msg}{Log.RESET}")
    @staticmethod
    def error(msg): print(f"{Log.RED}   [ERROR] {msg}{Log.RESET}")
    @staticmethod
    def retry(msg): print(f"{Log.MAGENTA}   [RETRY] {msg}{Log.RESET}")

if os.name == 'nt' and sys.stdout.isatty(): os.system('color')

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v", ".webm", ".ts"}
SRT_BLOCK_RE = re.compile(r"(?ms)^\s*\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*\n(.*?)(?=\n\s*\d+\s*\n|\s*\Z)")
WORKSPACE_ROOT_NAME = ".autosub_work"
WORKSPACE_MARKER_NAME = ".autosub-owned.json"

def run(cmd: List[str], cwd: Optional[Path] = None, dry_run: bool = False, timeout_seconds: Optional[int] = None) -> None:
    if dry_run:
        Log.info("[dry-run] " + " ".join(cmd))
        return
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and os.environ.get("AUTOSUB_GUI") == "1" else 0
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, timeout=timeout_seconds, creationflags=flags)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Subprocess timed out after {timeout_seconds}s: {' '.join(cmd)}") from e
    if p.returncode != 0:
        raise RuntimeError(f"Subprocess failed: {' '.join(cmd)}")

def ffprobe_duration_seconds(video: Path) -> Optional[float]:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)]
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and os.environ.get("AUTOSUB_GUI") == "1" else 0
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=30, creationflags=flags).strip()
        return float(out) if out else None
    except Exception:
        return None

def srt_has_text(path: Path) -> bool:
    try:
        return bool(read_srt(path))
    except (OSError, ValueError):
        return False


def is_valid_bilingual_srt(path: Path) -> bool:
    try:
        return all(len(block[3].splitlines()) >= 2 for block in read_srt(path))
    except (OSError, ValueError):
        return False


def translation_matches_source(source: Path, output: Path) -> bool:
    try:
        originals, translations = read_srt(source), read_srt(output)
        if len(originals) != len(translations):
            return False
        for original, translated in zip(originals, translations):
            lines = translated[3].splitlines()
            if original[:3] != translated[:3] or len(lines) != 2:
                return False
            if lines[0].strip() != "".join(line.strip() for line in original[3].splitlines()):
                return False
        return True
    except (OSError, ValueError):
        return False


def video_identity(video: Path, sample_size: int = 64 * 1024) -> dict:
    stat = video.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with video.open("rb") as stream:
        digest.update(stream.read(sample_size))
        if stat.st_size > sample_size:
            stream.seek(max(0, stat.st_size - sample_size))
            digest.update(stream.read(sample_size))
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sample_sha256": digest.hexdigest(),
    }

def state_matches_video(item: dict, identity: dict) -> bool:
    return isinstance(item, dict) and item.get("video_identity") == identity

def hide_output(path: Path) -> None:
    if os.name != "nt" or not path.exists():
        return
    try:
        subprocess.run(["attrib", "+h", str(path)], check=False, capture_output=True, text=True)
    except Exception:
        pass

def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unhide_output(path)
    atomic_write_json(path, state)
    hide_output(path)

def update_progress(state_path: Path, video: Path, **fields) -> None:
    if not state_path:
        return
    state = load_state(state_path)
    key = str(video.resolve())
    item = state.get(key, {})
    if not isinstance(item, dict):
        item = {}
    item.update(fields)
    item["updated_at"] = now_text()
    state[key] = item
    save_state(state_path, state)

def append_log(log_path: Path, video: Path, event: str, **fields) -> None:
    if not log_path:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    unhide_output(log_path)
    row = {
        "time": now_text(),
        "video": str(video.resolve()),
        "event": event,
        **fields,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    hide_output(log_path)

def unhide_output(path: Path) -> None:
    if os.name != "nt" or not path.exists():
        return
    try:
        subprocess.run(["attrib", "-h", "-r", str(path)], check=False, capture_output=True, text=True)
    except Exception:
        pass

def move_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        unhide_output(dst)
    os.replace(src, dst)

def backup_existing(path: Path, label: str) -> Path:
    unhide_output(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.{label}.{stamp}{path.suffix}")
    if backup.exists():
        backup = path.with_name(f"{path.stem}.{label}.{stamp}.{uuid.uuid4().hex[:8]}{path.suffix}")
    shutil.move(str(path), str(backup))
    Log.warn(f"Existing file preserved as backup: {backup.name}")
    return backup

def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "default"

def path_fingerprint(path: Path) -> str:
    normalized = str(path.resolve()).casefold().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:12]

def workspace_path(video: Path) -> Path:
    identity_hash = hashlib.sha256(json.dumps(video_identity(video), sort_keys=True).encode()).hexdigest()[:12]
    name = f"{safe_filename(video.stem)}.{path_fingerprint(video)}.{identity_hash}"
    return video.parent / WORKSPACE_ROOT_NAME / name

def prepare_workspace(video: Path) -> Path:
    work_dir = workspace_path(video)
    marker = work_dir / WORKSPACE_MARKER_NAME
    expected = str(video.resolve())

    if work_dir.exists():
        marker_data = load_state(marker)
        if marker_data.get("video") != expected:
            raise RuntimeError(f"Refusing to reuse unowned workspace: {work_dir}")
    else:
        work_dir.mkdir(parents=True)
        atomic_write_json(marker, {"video": expected, "created_at": now_text()})

    hide_output(work_dir.parent)
    return work_dir

def cleanup_workspace(video: Path, work_dir: Path) -> bool:
    expected = workspace_path(video)
    marker = work_dir / WORKSPACE_MARKER_NAME
    if work_dir.resolve() != expected.resolve():
        Log.warn(f"Workspace path check failed; preserving: {work_dir}")
        return False
    marker_data = load_state(marker)
    if marker_data.get("video") != str(video.resolve()):
        Log.warn(f"Workspace ownership marker missing or invalid; preserving: {work_dir}")
        return False

    try:
        shutil.rmtree(work_dir)
    except OSError as e:
        Log.warn(f"Could not clean workspace; preserving remaining files: {work_dir} ({e})")
        return False
    try:
        work_dir.parent.rmdir()
    except OSError:
        pass
    return True

def gcs_upload(bucket: str, object_name: str, local_file: Path) -> None:
    from google.cloud import storage

    Log.info(f"Uploading to GCS: gs://{bucket}/{object_name}")
    if not local_file.exists(): raise FileNotFoundError(local_file)
    client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
    b = client.bucket(bucket)
    blob = b.blob(object_name)
    blob.chunk_size = 256 * 1024 * 1024
    blob.upload_from_filename(str(local_file))

def gcs_delete(bucket: str, object_name: str) -> None:
    try:
        from google.cloud import storage

        client = storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
        blob = client.bucket(bucket).blob(object_name)
        blob.delete()
    except Exception as e:
        Log.warn(f"Could not delete temporary GCS object gs://{bucket}/{object_name}: {e}")

def call_sub_py(script_dir: Path, method: str, input_path: str, out_srt: Path, 
                timeout_hours: float, whisper_model: str, device: str, compute_type: str,
                hallucination_filter: str, dedupe_window_seconds: float, initial_prompt: str,
                local_timeout_minutes: int, dry_run: bool) -> None:
    cmd = [sys.executable, "sub.py", "--method", method, "--input", input_path, "--out", str(out_srt)]
    if method == "google":
        cmd.extend(["--timeout_hours", str(timeout_hours)])
    else:
        cmd.extend([
            "--model_size", whisper_model,
            "--device", device,
            "--compute_type", compute_type,
            "--hallucination_filter", hallucination_filter,
            "--dedupe_window_seconds", str(dedupe_window_seconds),
        ])
        if initial_prompt:
            cmd.extend(["--initial_prompt", initial_prompt])

    if method == "local":
        timeout_seconds = local_timeout_minutes * 60 if local_timeout_minutes else None
    else:
        timeout_seconds = int(timeout_hours * 3600) + 600
    
    run(cmd, cwd=script_dir, dry_run=dry_run, timeout_seconds=timeout_seconds)


def call_gemini_py(script_dir: Path, in_srt: Path, out_srt: Path,
                   project: str, location: str, model: str,
                   batch: int, sleep: float, timeout_minutes: int, checkpoint: Path, dry_run: bool) -> None:
    cmd = [
        sys.executable, "gemini.py",
        "--in", str(in_srt), "--out", str(out_srt),
        "--project", project, "--location", location, "--model", model,
        "--batch", str(batch), "--sleep", str(sleep), "--checkpoint", str(checkpoint),
    ]
    run(cmd, cwd=script_dir, dry_run=dry_run, timeout_seconds=timeout_minutes * 60)

def process_one(video: Path, args, script_dir: Path, state_path: Path, log_path: Path, checkpoint_dir: Path) -> int:
    stem = video.stem
    base_dir = video.parent
    work_dir = workspace_path(video)
    ja_out = base_dir / f"{stem}_ja.srt"
    bi_out = base_dir / f"{stem}.srt"
    video_state = load_state(state_path).get(str(video.resolve()), {}) if state_path else {}
    if getattr(args, "dry_run", False):
        state_path = log_path = None
    if not isinstance(video_state, dict):
        video_state = {}
    identity = video_identity(video)
    identity_known = isinstance(video_state.get("video_identity"), dict)
    state_is_stale = identity_known and not state_matches_video(video_state, identity)

    # 只有经过结构校验的双语字幕才算完成；显式 --force 时先备份再重做。
    if bi_out.exists():
        bi_valid = is_valid_bilingual_srt(bi_out)
        if bi_valid and state_is_stale and not args.force:
            Log.error(f"Existing bilingual SRT belongs to an older video at this path: {bi_out.name}. Use --force.")
            append_log(log_path, video, "stale_existing_output", output=str(bi_out))
            return 1
        if bi_valid and not args.force:
            Log.info(f"Skipping {video.name} - validated bilingual SRT already exists.")
            update_progress(state_path, video, status="complete", stage="done", output=str(bi_out), video_identity=identity)
            append_log(log_path, video, "skip_complete", output=str(bi_out))
            return 0
        if not args.force:
            Log.error(f"Existing bilingual SRT is invalid: {bi_out.name}. Use --force to back it up and rebuild.")
            append_log(log_path, video, "invalid_existing_output", output=str(bi_out))
            return 1
        if args.dry_run:
            Log.info(f"[dry-run] would back up existing output: {bi_out}")
        else:
            backup_existing(bi_out, "backup")

    ja_valid = ja_out.exists() and srt_has_text(ja_out)
    matched_no_text = video_state.get("status") == "no_text" and state_matches_video(video_state, identity)
    if ja_valid and state_is_stale and not args.force:
        Log.error(f"Existing Japanese SRT belongs to an older video at this path: {ja_out.name}. Use --force.")
        append_log(log_path, video, "stale_existing_ja", ja_srt=str(ja_out))
        return 1
    if args.force and ja_out.exists():
        if args.dry_run:
            Log.info(f"[dry-run] would back up existing Japanese SRT: {ja_out}")
        else:
            backup_existing(ja_out, "backup")
        ja_valid = False
    elif not ja_valid:
        if matched_no_text and not args.retry_no_text and not args.force:
            Log.warn(f"Skipping {video.name} - this exact video previously produced no subtitle text.")
            append_log(log_path, video, "skip_previous_no_text")
            return 0
        if ja_out.exists():
            if args.retry_no_text:
                if args.dry_run:
                    Log.info(f"[dry-run] would back up no-text Japanese SRT: {ja_out}")
                else:
                    backup_existing(ja_out, "no-text")
            else:
                Log.error(f"Existing Japanese SRT is empty or invalid: {ja_out.name}. Use --retry_no_text or --force.")
                append_log(log_path, video, "invalid_existing_ja", ja_srt=str(ja_out))
                return 1

    gcs_object = None
    gcs_uri = None
    if args.stt_mode == "cloud":
        gcs_object = f"autosub/{path_fingerprint(video)}/{uuid.uuid4().hex}/{stem}.stt.wav"
        gcs_uri = f"gs://{args.bucket}/{gcs_object}"

    duration = ffprobe_duration_seconds(video)
    local_args = argparse.Namespace(**vars(args))

    print("\n" + "-" * 60)
    Log.info(f"Processing: {Log.BOLD}{video.name}{Log.RESET}")
    Log.info(f"Location:   {base_dir}")
    if duration: Log.info(f"Duration:   {duration/60:.1f} min")
    Log.info(f"Mode:       STT={local_args.stt_mode} | Device={local_args.device}")
    print("-" * 60)

    if local_args.dry_run:
        wav_file = work_dir / f"{stem}.stt.wav"
        ja_tmp = work_dir / f"{stem}.ja.srt"
        bi_tmp = work_dir / f"{stem}.bilingual.srt"
        checkpoint = checkpoint_dir / f"{stem}.{path_fingerprint(video)}.{safe_filename(local_args.model)}.translate.part.json"

        Log.step("Step 1/4: Audio Extraction (FFmpeg)")
        run([sys.executable, "ffmpeg_only.py", str(video), "--out_dir", str(work_dir)], cwd=script_dir, dry_run=True)
        Log.step(f"Step 2/4: Speech-to-Text ({local_args.stt_mode.upper()})")
        if local_args.stt_mode == "cloud":
            Log.info(f"[dry-run] would upload audio to {gcs_uri}")
            call_sub_py(script_dir, "google", gcs_uri, ja_tmp, local_args.stt_timeout_hours,
                        "", "", "", "off", 0, "", 0, True)
        else:
            call_sub_py(script_dir, "local", str(wav_file), ja_tmp, 0,
                        local_args.whisper_model, local_args.device, local_args.compute_type,
                        local_args.hallucination_filter, local_args.dedupe_window_seconds,
                        local_args.initial_prompt, local_args.local_stt_timeout_minutes, True)
        Log.step("Step 3/4: AI Translation (Gemini)")
        call_gemini_py(script_dir, ja_tmp, bi_tmp, local_args.project, local_args.location,
                       local_args.model, local_args.batch, local_args.sleep,
                       local_args.translate_timeout_minutes, checkpoint, True)
        Log.step("Step 4/4: Finalizing")
        Log.info(f"[dry-run] would write {ja_out} and {bi_out}")
        return 0

    try:
        work_dir = prepare_workspace(video)
        update_progress(state_path, video, status="running", stage="start", work_dir=str(work_dir), model=local_args.model, video_identity=identity)
        append_log(log_path, video, "start", duration_minutes=round(duration / 60, 1) if duration else None, model=local_args.model)

        Log.step("Step 1/4: Audio Extraction (FFmpeg)")
        wav_file = work_dir / f"{stem}.stt.wav"
        if ja_valid:
             Log.info("Japanese SRT is ready; skipping audio extraction.")
        elif not local_args.force and wav_file.exists() and wav_file.stat().st_size > 0:
             Log.info("WAV file exists, skipping extraction.")
        else:
             run([sys.executable, "ffmpeg_only.py", str(video), "--out_dir", str(work_dir)], cwd=script_dir, dry_run=local_args.dry_run)
             Log.success("Audio extracted")
        update_progress(state_path, video, status="running", stage="audio", wav=str(wav_file))
        append_log(log_path, video, "audio_done", wav=str(wav_file))
        
        Log.step(f"Step 2/4: Speech-to-Text ({local_args.stt_mode.upper()})")
        ja_tmp = work_dir / f"{stem}.ja.srt"

        generated_ja = False
        ja_for_translate = ja_tmp
        if ja_valid:
            Log.info(f"Japanese SRT already exists, reusing: {ja_out.name}")
            ja_for_translate = ja_out
            Log.success("SRT Ready")
        else:
            stt_success = False
            for attempt in range(1, local_args.retries + 1):
                try:
                    if local_args.stt_mode == "cloud":
                        gcs_upload(local_args.bucket, gcs_object, wav_file)
                        try:
                            call_sub_py(script_dir, "google", gcs_uri, ja_tmp, local_args.stt_timeout_hours,
                                        "", "", "", "off", 0, "", 0, local_args.dry_run)
                        finally:
                            gcs_delete(local_args.bucket, gcs_object)
                    else:
                        call_sub_py(script_dir, "local", str(wav_file), ja_tmp, 0,
                                    local_args.whisper_model, local_args.device, local_args.compute_type,
                                    local_args.hallucination_filter, local_args.dedupe_window_seconds,
                                    local_args.initial_prompt, local_args.local_stt_timeout_minutes,
                                    local_args.dry_run)

                    stt_success = True
                    generated_ja = True
                    Log.success("SRT Generated")
                    break

                except Exception as e:
                    Log.warn(f"STT Attempt {attempt}/{local_args.retries} failed: {e}")
                    if attempt < local_args.retries:
                        Log.retry("Retrying in 5 seconds...")
                        time.sleep(5)
                    else:
                        raise e

            if not stt_success:
                raise RuntimeError("STT step failed.")

        update_progress(state_path, video, status="running", stage="stt", ja_srt=str(ja_for_translate))
        append_log(log_path, video, "stt_done", ja_srt=str(ja_for_translate))

        if not srt_has_text(ja_for_translate) and ja_for_translate.read_text(encoding="utf-8-sig").strip():
            raise RuntimeError(f"STT produced malformed subtitles: {ja_for_translate}")
        if not srt_has_text(ja_for_translate):
            Log.warn("STT produced no subtitle text. Skipping Gemini translation.")
            if not local_args.dry_run:
                if generated_ja:
                    move_replace(ja_tmp, ja_out)
                    hide_output(ja_out)
                if not local_args.keep_workspace:
                    cleanup_workspace(video, work_dir)
            update_progress(state_path, video, status="no_text", stage="stt", ja_srt=str(ja_out if generated_ja else ja_for_translate), video_identity=identity)
            append_log(log_path, video, "no_text", ja_srt=str(ja_out if generated_ja else ja_for_translate))
            return 0

        if generated_ja and not local_args.dry_run:
            move_replace(ja_tmp, ja_out)
            hide_output(ja_out)
            ja_for_translate = ja_out
            generated_ja = False
            update_progress(state_path, video, status="running", stage="stt_saved", ja_srt=str(ja_out))
            append_log(log_path, video, "stt_saved", ja_srt=str(ja_out))

        Log.step("Step 3/4: AI Translation (Gemini)")
        bi_tmp = work_dir / f"{stem}.bilingual.srt"
        checkpoint = checkpoint_dir / f"{stem}.{path_fingerprint(video)}.{safe_filename(local_args.model)}.translate.part.json"
        
        for attempt in range(1, local_args.retries + 1):
            try:
                update_progress(state_path, video, status="running", stage="translate", checkpoint=str(checkpoint), attempt=attempt)
                append_log(log_path, video, "translate_start", attempt=attempt, checkpoint=str(checkpoint))
                call_gemini_py(script_dir, ja_for_translate, bi_tmp, local_args.project, local_args.location, local_args.model, local_args.batch, local_args.sleep, local_args.translate_timeout_minutes, checkpoint, local_args.dry_run)
                if not translation_matches_source(ja_for_translate, bi_tmp):
                    raise RuntimeError(f"Translation output failed bilingual SRT validation: {bi_tmp}")
                Log.success("Translation Complete")
                update_progress(state_path, video, status="running", stage="translated", bilingual_tmp=str(bi_tmp))
                append_log(log_path, video, "translate_done", bilingual_tmp=str(bi_tmp))
                break
            except Exception as e:
                Log.warn(f"Translate Attempt {attempt}/{local_args.retries} failed: {e}")
                update_progress(state_path, video, status="retrying", stage="translate", error=str(e), attempt=attempt, checkpoint=str(checkpoint))
                append_log(log_path, video, "translate_failed", attempt=attempt, error=str(e), checkpoint=str(checkpoint))
                if attempt < local_args.retries:
                    Log.retry("Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    raise e

        Log.step("Step 4/4: Finalizing")
        if not local_args.dry_run:
            if generated_ja:
                move_replace(ja_tmp, ja_out)
            move_replace(bi_tmp, bi_out)
            hide_output(ja_out)
            hide_output(bi_out)
            if not local_args.keep_workspace:
                cleanup_workspace(video, work_dir)
        update_progress(state_path, video, status="complete", stage="done", ja_srt=str(ja_out), output=str(bi_out), video_identity=identity)
        append_log(log_path, video, "complete", ja_srt=str(ja_out), output=str(bi_out))

        Log.success(f"All Done! Output:\n      -> {bi_out.name}")
        return 0

    except Exception as e:
        Log.error(f"Failed: {e}")
        update_progress(state_path, video, status="failed", stage="error", error=str(e), work_dir=str(work_dir))
        append_log(log_path, video, "failed", error=str(e), work_dir=str(work_dir))
        if not local_args.dry_run:
            if local_args.keep_workspace or not local_args.always_cleanup:
                Log.warn(f"Workspace preserved: {work_dir}")
            else:
                if cleanup_workspace(video, work_dir):
                    Log.info(f"Workspace cleaned: {work_dir}")
        return 1

def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed

def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed

def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed

def non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed

def main():
    from gui_support import DEFAULTS as CONFIG_DEFAULTS, SETTINGS_PATH, load_settings
    config_arg = argparse.ArgumentParser(add_help=False)
    config_arg.add_argument("--version", action="version", version=__version__)
    config_arg.add_argument("--config", type=Path, default=SETTINGS_PATH)
    config_arg.add_argument("--no_config", action="store_true")
    preliminary, _ = config_arg.parse_known_args()
    if not preliminary.no_config and preliminary.config != SETTINGS_PATH and not preliminary.config.is_file():
        config_arg.error(f"config does not exist: {preliminary.config}")
    try:
        config = CONFIG_DEFAULTS.copy() if preliminary.no_config else load_settings(preliminary.config)
    except (OSError, ValueError) as exc:
        config_arg.error(str(exc))
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("input", nargs="?", help="Video file, SRT file or directory")
    ap.add_argument("--config", type=Path, default=SETTINGS_PATH, help="JSON configuration file")
    ap.add_argument("--no_config", action="store_true", help="use command-line settings without loading a config file")
    ap.add_argument("--bucket")
    ap.add_argument("--project", default="")
    ap.add_argument("--gemini_backend", choices=["developer", "vertex"], default="developer")
    ap.add_argument("--source_language", default="auto")
    ap.add_argument("--target_language", default="zh-CN")
    ap.add_argument("--output_mode", choices=["bilingual", "translated"], default="bilingual")
    ap.add_argument("--cloud_language_code", default="")
    ap.add_argument("--stt_mode", choices=["cloud", "local"], default="local")
    ap.add_argument("--whisper_model", default="large-v3")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute_type", default="default")
    ap.add_argument("--hallucination_filter", choices=["off", "conservative", "aggressive"], default="off")
    ap.add_argument("--dedupe_window_seconds", type=non_negative_float, default=0.1)
    ap.add_argument("--initial_prompt", default="")
    ap.add_argument("--local_stt_timeout_minutes", type=non_negative_int, default=0,
                    help="0 disables the local Whisper timeout")
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--stt_timeout_hours", type=positive_float, default=3.0)
    ap.add_argument("--batch", type=positive_int, default=20)
    ap.add_argument("--sleep", type=non_negative_float, default=1.0)
    ap.add_argument("--translate_timeout_minutes", type=positive_int, default=10)
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--stop_file", type=Path, help="stop before the next video when this file exists")
    ap.add_argument("--gui_events", action="store_true", help=argparse.SUPPRESS)
    retry_group = ap.add_mutually_exclusive_group()
    retry_group.add_argument("--force", action="store_true", help="back up existing subtitles and rebuild")
    retry_group.add_argument("--retry_no_text", action="store_true", help="retry a matching no-text result")
    cleanup_group = ap.add_mutually_exclusive_group()
    cleanup_group.add_argument("--always_cleanup", action="store_true")
    cleanup_group.add_argument("--keep_workspace", action="store_true")
    ap.add_argument("--no_progress_log", action="store_true", help="disable the progress log while keeping recovery state")
    ap.add_argument("--retries", type=positive_int, default=3)

    config_values = {key: value for key, value in config.items()
                     if key not in {"api_key", "credentials", "existing", "keep_workspace"} and key in CONFIG_DEFAULTS}
    ap.set_defaults(**config_values)

    args = ap.parse_args()
    if not args.input:
        ap.error("choose an input file or directory, or set input in config.json")
    if not args.force and not args.retry_no_text:
        args.force = config["existing"] == "force"
        args.retry_no_text = config["existing"] == "retry_no_text"
    if config["keep_workspace"] and not args.always_cleanup:
        args.keep_workspace = True
    if config["credentials"].strip() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = config["credentials"].strip()
    if args.gemini_backend == "developer" and config["api_key"].strip() and not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = config["api_key"].strip()
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
    try:
        args.source_language = language_tag(args.source_language, allow_auto=True)
        args.target_language = language_tag(args.target_language)
    except ValueError as exc:
        ap.error(str(exc))
    args.new_pipeline = True
    script_dir = Path(__file__).resolve().parent
    inp = Path(args.input).expanduser().resolve()
    if not inp.exists():
        ap.error(f"input does not exist: {inp}")
    if inp.is_file() and inp.suffix.lower() not in VIDEO_EXTS | {".srt"}:
        ap.error(f"unsupported video extension: {inp.suffix or '(none)'}")
    needs_stt = inp.suffix.lower() != ".srt"
    if needs_stt and args.stt_mode == "cloud":
        if not args.project or not args.bucket:
            ap.error("cloud speech requires --project and --bucket")
        if args.source_language == "auto" and not args.cloud_language_code:
            ap.error("cloud speech with auto source requires --cloud_language_code")
        if not args.cloud_language_code:
            args.cloud_language_code = SPEECH_CODES.get(args.source_language, args.source_language)
        os.environ["GOOGLE_CLOUD_PROJECT"] = args.project
    if args.gemini_backend == "vertex" and not args.project:
        ap.error("Vertex translation requires --project")
    progress_root = inp if inp.is_dir() else inp.parent
    state_path = progress_root / ".autosub_state.json"
    log_path = progress_root / ".autosub_progress.jsonl"
    checkpoint_dir = progress_root / ".autosub_checkpoints"
    if args.no_progress_log:
        log_path = None
    
    # 【核心修改区】
    if inp.is_dir():
        # rglob("*") 会递归搜索所有子文件夹，并筛选出后缀匹配的视频文件
        videos = sorted([p for p in inp.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS])
        print(f"[{Log.GREEN}Auto-Discovery{Log.RESET}] Found {len(videos)} videos in '{inp.name}' and its subfolders.")
    else:
        videos = [inp]

    if not videos:
        ap.error(f"no supported video files found under: {inp}")

    output_targets = {}
    for video in videos:
        for target in ((output_path(video, args.target_language, args.output_mode),) if video.suffix.lower() == ".srt"
                       else (output_path(video, args.target_language, args.output_mode),
                             source_path(video, args.source_language))):
            target_key = str(target.resolve()).casefold()
            if target_key in output_targets:
                ap.error(f"multiple videos would write the same output: {output_targets[target_key]} and {video}")
            output_targets[target_key] = video

    if args.stt_mode == "local" and args.device == "cpu":
        if args.compute_type == "float16":
            args.compute_type = "int8"

    lock_dirs = [progress_root] + [video.parent for video in videos]
    try:
        with (nullcontext() if args.dry_run else batch_locks(lock_dirs)):
            code = run_batch(videos, args, script_dir, state_path, log_path, checkpoint_dir)
    except (OSError, RuntimeError) as exc:
        Log.error(str(exc))
        code = 1
    sys.exit(code)


def gui_event(args, event, **fields):
    if getattr(args, "gui_events", False):
        print("__AUTOSUB_EVENT__" + json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def run_batch(videos, args, script_dir, state_path, log_path, checkpoint_dir):
    failures = completed = 0
    total = len(videos)
    def batch_log(event, **fields):
        if log_path and not getattr(args, "dry_run", False):
            try:
                append_log(log_path, log_path.parent, event, **fields)
            except OSError as exc:
                Log.warn(f"Could not write batch log: {exc}")
    batch_log("batch_start", total=total)
    gui_event(args, "batch_start", total=total)
    for video in videos:
        if getattr(args, "stop_file", None) and args.stop_file.exists():
            batch_log("batch_stopped", total=total, completed=completed, failed=failures)
            gui_event(args, "batch_done", total=total, completed=completed, failed=failures, stopped=True)
            Log.info("Stopped before the next video. Existing results and checkpoints are preserved.")
            return 130
        gui_event(args, "video_start", video=str(video), index=completed + 1, total=total)
        try:
            if getattr(args, "new_pipeline", False):
                from pipeline import process_input
                result = process_input(video, args, script_dir, state_path, log_path, checkpoint_dir)
            else:
                result = process_one(video, args, script_dir, state_path, log_path, checkpoint_dir)
        except Exception as exc:
            # Includes failures before process_one's processing try block.
            Log.error(f"Cannot process {video.name}: {exc}")
            result = 1
        completed += 1
        failures += int(result != 0)
        gui_event(args, "video_done", video=str(video), completed=completed, total=total, failed=failures)
    Log.info(f"Batch complete. Total: {total}, Failed: {failures}")
    batch_log("batch_done", total=total, completed=completed, failed=failures)
    gui_event(args, "batch_done", total=total, completed=completed, failed=failures, stopped=False)
    return 1 if failures else 0


if __name__ == "__main__":
    main()
