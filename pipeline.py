"""Source-aware video and SRT pipeline for the multilingual interface."""
import hashlib
import os
import uuid
from pathlib import Path

import main as core
from translation_config import redact
from language_config import normalized_text, output_identity, output_path, source_path
from language_config import stt_identity, translation_identity, SPEECH_CODES
from srt_utils import read_srt


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def valid_translation(source, output, source_language, mode):
    try:
        originals, result = read_srt(source), read_srt(output)
    except (OSError, ValueError):
        return False
    if len(originals) != len(result):
        return False
    for original, translated in zip(originals, result):
        if original[:3] != translated[:3]:
            return False
        if mode == "bilingual":
            lines = translated[3].splitlines()
            if len(lines) != 2 or lines[0] != normalized_text(original[3], source_language) or not lines[1].strip():
                return False
        elif not translated[3].strip():
            return False
    return True


def source_ready(path):
    try:
        return bool(read_srt(path))
    except (OSError, ValueError):
        return False


def cached_translations(state, source, desired_output, translation_key, source_language):
    records = state.get("outputs", {}) if isinstance(state.get("outputs"), dict) else {}
    for raw_path, record in records.items():
        candidate = Path(raw_path)
        if candidate == desired_output or not isinstance(record, dict) or record.get("translation_identity") != translation_key:
            continue
        if not candidate.is_file() or record.get("sha256") != file_sha256(candidate):
            continue
        mode = "bilingual" if candidate.name.endswith(".bilingual.srt") else "translated"
        if not valid_translation(source, candidate, source_language, mode):
            continue
        blocks = read_srt(candidate)
        return [block[3].splitlines()[1] if mode == "bilingual" else block[3] for block in blocks]
    return None


def render_translations(path, source, translations, source_language, target_language, mode):
    blocks = read_srt(source)
    if len(blocks) != len(translations):
        raise RuntimeError("Cached translation count mismatch")
    with Path(path).open("w", encoding="utf-8") as stream:
        for block, translated in zip(blocks, translations):
            text = normalized_text(translated, target_language)
            body = (normalized_text(block[3], source_language) + "\n" + text
                    if mode == "bilingual" else text)
            stream.write(f"{block[0]}\n{block[1]} --> {block[2]}\n{body}\n\n")


def _save_status(state_path, source, **fields):
    core.update_progress(state_path, source, **fields)


def process_input(inp, args, script_dir, state_path, log_path, checkpoint_dir):
    from pipeline_job import PipelineJob
    from task_state import StateStore
    job = None
    try:
        job = PipelineJob(inp, args, script_dir, StateStore(state_path, log_path), checkpoint_dir)
        if job.phase in ("complete", "no_text"):
            core.Log.info(f"Reusing verified {job.phase}: {inp}")
            return 0
        if args.dry_run:
            core.Log.info(f"[dry-run] input={inp} source={job.original} output={job.output} --model {args.model}")
            if job.phase != "source_ready":
                core.Log.step("Step 1/4: Audio Extraction (FFmpeg)")
                core.Log.step(f"Step 2/4: Speech-to-Text ({args.stt_mode.upper()})")
            core.Log.step(f"Step 3/4: AI Translation ({job.translation.label})")
            core.Log.step("Step 4/4: Finalizing")
            return 0
        job.start()
        if job.phase == "pending":
            job.begin_extract()
            core.Log.step("Step 1/4: Audio Extraction (FFmpeg)")
            job.extract()
            job.commit_audio()
        if job.phase == "audio_ready":
            job.begin_stt()
            core.Log.step(f"Step 2/4: Speech-to-Text ({args.stt_mode.upper()})")
            job.recognize()
            job.commit_source()
        if job.phase == "no_text":
            return 0
        job.begin_translation()
        core.Log.step(f"Step 3/4: AI Translation ({job.translation.label})")
        job.translate()
        core.Log.step("Step 4/4: Finalizing")
        job.finalize()
        return 0
    except Exception as exc:
        if job is not None and not args.dry_run:
            job.fail(exc)
        core.Log.error(f"Failed: {redact(exc)}")
        return 1
