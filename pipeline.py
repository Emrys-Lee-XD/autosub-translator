"""Source-aware video and SRT pipeline for the multilingual interface."""
import hashlib
import os
import uuid
from pathlib import Path

import main as core
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
    inp = Path(inp)
    is_srt = inp.suffix.lower() == ".srt"
    video_identity = {"source_sha256": file_sha256(inp)} if is_srt else core.video_identity(inp)
    state = core.load_state(state_path).get(str(inp.resolve()), {}) if state_path else {}
    if not isinstance(state, dict):
        state = {}
    stt_key = None if is_srt else stt_identity(args)
    original = inp if is_srt else source_path(inp, args.source_language)
    output = output_path(inp, args.target_language, args.output_mode)
    state_matches = state.get("video_identity") == video_identity
    source_valid = source_ready(original)
    if is_srt and not source_valid:
        core.Log.error(f"Input SRT is empty or invalid: {inp}")
        return 1
    source_hash = file_sha256(original) if source_valid else None
    can_reuse_source = is_srt or (source_valid and state_matches and
                                  state.get("stt_identity") == stt_key and
                                  state.get("source_sha256") == source_hash)
    translation_key = translation_identity(args, source_hash) if source_hash else None
    render_key = output_identity(args, source_hash) if source_hash else None
    cached = (cached_translations(state, original, output, translation_key, args.source_language)
              if source_hash and can_reuse_source and state_matches and not args.force else None)
    output_record = state.get("outputs", {}).get(str(output)) if isinstance(state.get("outputs"), dict) else None

    known_output = state_matches and isinstance(output_record, dict)
    if output.exists() and not args.force:
        if (state_matches and can_reuse_source and isinstance(output_record, dict) and
            output_record.get("translation_identity") == translation_key and
            output_record.get("output_identity") == render_key and
            output_record.get("sha256") == file_sha256(output) and
            valid_translation(original, output, args.source_language, args.output_mode)):
            core.Log.info(f"Reusing verified output: {output}")
            return 0
        if not known_output:
            core.Log.error(f"Existing output has unknown provenance: {output}. Use --force to back it up.")
            return 1

    if not is_srt and not args.force and not args.retry_no_text and state_matches and state.get("status") == "no_text" and state.get("stt_identity") == stt_key:
        core.Log.info(f"Skipping matching no-text result: {inp.name}")
        return 0

    known_source = (state_matches and state.get("stt_identity") and
                    state.get("source_sha256") == source_hash)
    if source_valid and not can_reuse_source and not is_srt and not (args.force or known_source):
        core.Log.error(f"Existing source subtitles have unknown provenance: {original}. Use --force to back them up.")
        return 1
    known_empty_source = state_matches and state.get("status") == "no_text" and original.exists() and not source_valid
    if original.exists() and not source_valid and not is_srt and not (args.force or args.retry_no_text or known_empty_source):
        core.Log.error(f"Existing source subtitles are empty or invalid: {original}. Use --retry_no_text or --force.")
        return 1

    if args.dry_run:
        core.Log.info(f"[dry-run] input={inp} source={original} output={output} --model {args.model}")
        if output.exists():
            core.Log.info(f"[dry-run] would back up output: {output}")
        if not is_srt and (args.force or args.retry_no_text or not can_reuse_source) and original.exists():
            core.Log.info(f"[dry-run] would back up source: {original}")
        if not can_reuse_source and not is_srt:
            core.Log.step("Step 1/4: Audio Extraction (FFmpeg)")
            core.Log.step(f"Step 2/4: Speech-to-Text ({args.stt_mode.upper()})")
        core.Log.step("Step 3/4: AI Translation (Gemini)")
        core.Log.step("Step 4/4: Finalizing")
        return 0

    if cached is None and args.gemini_backend == "developer" and not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        core.Log.error("Gemini API Key is missing. Enter it in the GUI or set GEMINI_API_KEY.")
        return 1

    work_dir = core.prepare_workspace(inp)
    output_tmp = work_dir / f"{uuid.uuid4().hex}.translated.srt"
    if not is_srt and original.exists() and (args.force or not can_reuse_source):
        core.backup_existing(original, "backup")
        can_reuse_source = False

    try:
        if not can_reuse_source:
            wav = work_dir / f"{inp.stem}.stt.wav"
            if args.force or not wav.is_file() or wav.stat().st_size == 0:
                core.Log.step("Step 1/4: Audio Extraction (FFmpeg)")
                core.run([core.sys.executable, "ffmpeg_only.py", str(inp), "--out_dir", str(work_dir)], cwd=script_dir)
            core.Log.step(f"Step 2/4: Speech-to-Text ({args.stt_mode.upper()})")
            source_tmp = work_dir / f"{uuid.uuid4().hex}.source.srt"
            if args.stt_mode == "cloud":
                object_name = f"autosub/{core.path_fingerprint(inp)}/{uuid.uuid4().hex}/{inp.stem}.stt.wav"
                uri = f"gs://{args.bucket}/{object_name}"
                core.gcs_upload(args.bucket, object_name, wav)
                try:
                    code = args.cloud_language_code or SPEECH_CODES.get(args.source_language, args.source_language)
                    core.run([core.sys.executable, "sub.py", "--method", "google", "--input", uri,
                              "--out", str(source_tmp), "--lang", code,
                              "--project", args.project,
                              "--source_language", args.source_language,
                              "--timeout_hours", str(args.stt_timeout_hours)], cwd=script_dir,
                             timeout_seconds=int(args.stt_timeout_hours * 3600) + 600)
                finally:
                    core.gcs_delete(args.bucket, object_name)
            else:
                cmd = [core.sys.executable, "sub.py", "--method", "local", "--input", str(wav),
                       "--out", str(source_tmp), "--source_language", args.source_language,
                       "--model_size", args.whisper_model, "--device", args.device,
                       "--compute_type", args.compute_type,
                       "--hallucination_filter", args.hallucination_filter,
                       "--dedupe_window_seconds", str(args.dedupe_window_seconds)]
                if args.initial_prompt:
                    cmd.extend(["--initial_prompt", args.initial_prompt])
                core.run(cmd, cwd=script_dir,
                         timeout_seconds=args.local_stt_timeout_minutes * 60 or None)
            if not source_tmp.is_file():
                raise RuntimeError("Speech recognition did not create an SRT file")
            if not source_ready(source_tmp):
                if source_tmp.exists() and source_tmp.read_text(encoding="utf-8-sig").strip():
                    raise RuntimeError(f"Speech recognition produced invalid SRT: {source_tmp}")
                if source_tmp.exists():
                    core.move_replace(source_tmp, original)
                _save_status(state_path, inp, status="no_text", video_identity=video_identity,
                             stt_identity=stt_key, source_sha256=None)
                core.Log.warn(f"No speech text found: {inp.name}")
                if not args.keep_workspace:
                    core.cleanup_workspace(inp, work_dir)
                return 0
            core.move_replace(source_tmp, original)
            core.hide_output(original)
        source_hash = file_sha256(original)
        _save_status(state_path, inp, status="source_ready", video_identity=video_identity,
                     stt_identity=stt_key, source_sha256=source_hash)
        translation_key = translation_identity(args, source_hash)
        render_key = output_identity(args, source_hash)
        checkpoint = checkpoint_dir / f"{core.path_fingerprint(inp)}.{translation_key[:24]}.part.json"
        if args.force:
            checkpoint.unlink(missing_ok=True)
        cmd = [core.sys.executable, "gemini.py", "--in", str(original), "--out", str(output_tmp),
               "--backend", args.gemini_backend, "--model", args.model,
               "--source_language", args.source_language, "--target_language", args.target_language,
               "--output_mode", args.output_mode, "--checkpoint", str(checkpoint),
               "--batch", str(args.batch), "--sleep", str(args.sleep),
               "--line_retries", str(args.retries)]
        if args.gemini_backend == "vertex":
            cmd.extend(["--project", args.project, "--location", args.location])
        core.Log.step("Step 3/4: AI Translation (Gemini)")
        if cached is not None:
            render_translations(output_tmp, original, cached, args.source_language,
                                args.target_language, args.output_mode)
            core.Log.info("Reformatted previously verified translations")
        else:
            core.run(cmd, cwd=script_dir, timeout_seconds=args.translate_timeout_minutes * 60)
        if not valid_translation(original, output_tmp, args.source_language, args.output_mode):
            raise RuntimeError("Translated SRT does not match source timing/content")
        core.Log.step("Step 4/4: Finalizing")
        if output.exists():
            core.backup_existing(output, "backup")
        core.move_replace(output_tmp, output)
        core.unhide_output(output)
        outputs = state.get("outputs", {}) if isinstance(state.get("outputs"), dict) else {}
        outputs[str(output)] = {"translation_identity": translation_key,
                                "output_identity": render_key, "sha256": file_sha256(output)}
        _save_status(state_path, inp, status="complete", video_identity=video_identity,
                     stt_identity=stt_key, source_sha256=source_hash,
                     translation_identity=translation_key, output_identity=render_key,
                     output=str(output), outputs=outputs)
        core.Log.success(f"Created: {output}")
        if not args.keep_workspace:
            core.cleanup_workspace(inp, work_dir)
        return 0
    except Exception as exc:
        _save_status(state_path, inp, status="failed", error=str(exc),
                     video_identity=video_identity, stt_identity=stt_key)
        core.Log.error(f"Failed: {exc}")
        return 1
