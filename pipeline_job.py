"""Shared stage operations for ordinary and Turbo scheduling."""
import copy
import json
import os
import uuid
import wave
from pathlib import Path

import main as core
from language_config import (identity, output_identity, output_path, source_path,
                             stt_identity, translation_identity, SPEECH_CODES)
from translation_config import TranslationConfig, redact
from pipeline import file_sha256, source_ready, valid_translation, cached_translations, render_translations


def valid_audio(path):
    try:
        with wave.open(str(path), "rb") as stream:
            if not (stream.getnchannels() == 1 and stream.getframerate() == 16000 and
                    stream.getsampwidth() == 2 and stream.getnframes() > 0):
                return False
            stream.setpos(stream.getnframes() - 1)
            return len(stream.readframes(1)) == 2
    except (OSError, EOFError, wave.Error):
        return False


class PipelineJob:
    def __init__(self, inp, args, script_dir, store, checkpoint_dir):
        self.inp = Path(inp).resolve()
        self.args = copy.copy(args)
        self.translation = TranslationConfig.from_values(self.args)
        self.script_dir, self.store = script_dir, store
        self.checkpoint_dir = Path(checkpoint_dir)
        self.job_id = core.path_fingerprint(self.inp)
        self.is_srt = self.inp.suffix.lower() == ".srt"
        self.video_id = self.input_identity()
        self.stt_key = None if self.is_srt else stt_identity(args)
        self.original = self.inp if self.is_srt else source_path(self.inp, args.source_language)
        self.output = output_path(self.inp, args.target_language, args.output_mode)
        self.state = store.get(self.inp)
        self.phase = "pending"
        self.started = False
        self.attempt = None
        self.work_dir = self.wav = self.source_tmp = self.output_tmp = None
        self.cached = None
        self.retries = 0
        self.translation_initialized = False
        self.prepare()

    def input_identity(self):
        return {"source_sha256": file_sha256(self.inp)} if self.is_srt else core.video_identity(self.inp)

    def ensure_unchanged(self):
        if self.input_identity() != self.video_id:
            raise RuntimeError("Input changed while processing; existing results preserved")

    def prepare(self):
        args, state = self.args, self.state
        matches = state.get("video_identity") == self.video_id
        valid = source_ready(self.original)
        if self.is_srt and not valid:
            raise RuntimeError(f"Input SRT is empty or invalid: {self.inp}")
        self.source_hash = file_sha256(self.original) if valid else None
        # Recover an atomic source/output commit interrupted before its final state save.
        pending = state.get("source_pending", {})
        pending_source = (matches and not args.force and self.original.is_file() and isinstance(pending, dict) and
                pending.get("stt_identity") == self.stt_key and
                pending.get("sha256") == file_sha256(self.original))
        if pending_source:
            if not valid and self.original.read_text(encoding="utf-8-sig").strip():
                raise RuntimeError("Interrupted source commit has invalid subtitles")
            state.update(stt_identity=self.stt_key, source_sha256=self.source_hash,
                         status="source_ready" if valid else "no_text")
            if not args.dry_run:
                self.save(status=state["status"], stage=state["status"], stt_identity=self.stt_key,
                          source_sha256=self.source_hash, source_attempt=None, source_pending=None, audio=None)
        reusable = self.is_srt or (matches and valid and state.get("stt_identity") == self.stt_key and
                                   state.get("source_sha256") == self.source_hash)
        key = translation_identity(args, self.source_hash) if self.source_hash else None
        render_key = output_identity(args, self.source_hash) if self.source_hash else None
        records = state.get("outputs", {})
        record = records.get(str(self.output)) if isinstance(records, dict) else None
        pending_output = state.get("output_pending", {})
        if (matches and reusable and not args.force and isinstance(pending_output, dict) and
                pending_output.get("path") == str(self.output) and
                pending_output.get("translation_identity") == key and
                pending_output.get("output_identity") == render_key):
            record = pending_output
        if self.output.exists() and not args.force:
            if (matches and reusable and isinstance(record, dict) and
                    record.get("translation_identity") == key and record.get("output_identity") == render_key and
                    record.get("sha256") == file_sha256(self.output) and
                    valid_translation(self.original, self.output, args.source_language, args.output_mode)):
                self.phase = "complete"
                if record is pending_output and not args.dry_run:
                    outputs = dict(records) if isinstance(records, dict) else {}
                    outputs[str(self.output)] = record
                    self.save(status="complete", stage="done", outputs=outputs, output=str(self.output),
                              translation_identity=key, output_identity=render_key, output_pending=None,
                              translation_attempt=None, translation_pending=None, error=None)
                return
            if not (matches and isinstance(record, dict)):
                raise RuntimeError(f"Existing output has unknown provenance: {self.output}. Use --force to back it up.")
        empty_source = not self.original.exists() or (not valid and not self.original.read_text(encoding="utf-8-sig").strip())
        if (not self.is_srt and not args.force and not args.retry_no_text and matches and empty_source and
                state.get("status") == "no_text" and state.get("stt_identity") == self.stt_key):
            self.phase = "no_text"
            return
        known_source = matches and state.get("stt_identity") and state.get("source_sha256") == self.source_hash
        if valid and not reusable and not self.is_srt and not (args.force or known_source):
            raise RuntimeError(f"Existing source subtitles have unknown provenance: {self.original}. Use --force to back them up.")
        empty_known = matches and state.get("status") == "no_text" and empty_source
        if (self.original.exists() and not valid and not self.is_srt and
                not (args.force or args.retry_no_text or empty_known)):
            raise RuntimeError(f"Existing source subtitles are empty or invalid: {self.original}. Use --retry_no_text or --force.")
        if self.is_srt or (reusable and not args.force):
            self.phase = "source_ready"
        self.cached = (cached_translations(state, self.original, self.output, key, args.source_language)
                       if reusable and matches and not args.force else None)
        if not args.dry_run and self.cached is None:
            self.translation.validate_auth()

    def save(self, **fields):
        self.state = self.store.update(self.inp, video_identity=self.video_id, **fields)

    def log(self, event, **fields):
        self.store.log(self.inp, event, job_id=self.job_id, **fields)

    def start(self):
        if self.started:
            return
        self.ensure_unchanged()
        self.work_dir = core.prepare_workspace(self.inp)
        self.wav = self.work_dir / f"{self.inp.stem}.stt.wav"
        self.audio_proof = self.work_dir / "audio.done.json"
        self.output_tmp = self.work_dir / f"{uuid.uuid4().hex}.translated.srt"
        self.started = True
        if self.phase == "pending" and not self.args.force:
            pending = self.state.get("source_attempt", {})
            if isinstance(pending, dict) and pending.get("stt_identity") == self.stt_key:
                candidate = Path(pending.get("path", ""))
                if (self.state.get("video_identity") == self.video_id and
                        candidate.parent == self.work_dir and candidate.name.endswith(".source.srt") and
                        candidate.is_file() and (source_ready(candidate) or not candidate.read_text(encoding="utf-8-sig").strip())):
                    self.source_tmp = candidate
                    self.commit_source()
                    return
            audio = self.state.get("audio", {})
            if (isinstance(audio, dict) and audio.get("identity") == self.audio_identity() and
                    audio.get("path") == str(self.wav) and self.wav.is_file() and
                    audio.get("size") == self.wav.stat().st_size and valid_audio(self.wav)):
                self.phase = "audio_ready"
            elif (self.state.get("audio_attempt") == self.audio_identity() and
                  self.state.get("video_identity") == self.video_id and self.audio_completed()):
                self.commit_audio()
        self.save(status=self.phase, stage=self.phase, error=None, stt_identity=self.stt_key,
                  work_dir=str(self.work_dir))
        if self.phase == "source_ready" and not self.is_srt and not self.args.keep_workspace:
            self.wav.unlink(missing_ok=True)

    def audio_identity(self):
        return identity(dict(video=self.video_id, channels=1, rate=16000, format="pcm_s16le", version=1))

    def audio_completed(self):
        try:
            proof = json.loads(self.audio_proof.read_text(encoding="utf-8"))
            return (isinstance(proof, dict) and proof.get("identity") == self.audio_identity() and
                    proof.get("size") == self.wav.stat().st_size and valid_audio(self.wav))
        except (OSError, ValueError):
            return False

    def begin_extract(self):
        self.start()
        if self.phase != "pending":
            return False
        self.audio_proof.unlink(missing_ok=True)
        self.phase = "extracting"
        self.save(status="running", stage=self.phase, audio_attempt=self.audio_identity())
        return True

    def extract(self, runner=None):
        (runner or core.run)([core.sys.executable, "ffmpeg_only.py", str(self.inp),
                              "--out_dir", str(self.work_dir)], cwd=self.script_dir)
        if not valid_audio(self.wav):
            raise RuntimeError("Extraction did not create a complete 16 kHz mono PCM WAV")
        # This private artifact proves successful FFmpeg exit before a crash.
        # A valid-looking WAV alone may be a finalized partial/failed extraction.
        core.atomic_write_json(self.audio_proof, dict(identity=self.audio_identity(), size=self.wav.stat().st_size))

    def commit_audio(self):
        self.ensure_unchanged()
        if not valid_audio(self.wav):
            raise RuntimeError("Extraction did not create a complete 16 kHz mono PCM WAV")
        self.phase = "audio_ready"
        self.save(status=self.phase, stage=self.phase,
                  audio=dict(identity=self.audio_identity(), path=str(self.wav), size=self.wav.stat().st_size),
                  audio_attempt=None)

    def stt_config(self):
        return dict(model_size=self.args.whisper_model, device=self.args.device,
                    compute_type=self.args.compute_type, source_language=self.args.source_language,
                    initial_prompt=self.args.initial_prompt, hallucination_filter=self.args.hallucination_filter,
                    dedupe_window_seconds=self.args.dedupe_window_seconds)

    def begin_stt(self):
        self.attempt = uuid.uuid4().hex
        self.source_tmp = self.work_dir / f"{self.attempt}.source.srt"
        self.phase = "recognizing"
        self.save(status="running", stage=self.phase, stt_identity=self.stt_key,
                  source_attempt=dict(path=str(self.source_tmp), stt_identity=self.stt_key, attempt=self.attempt))

    def recognize(self):
        args = self.args
        if args.stt_mode == "cloud":
            obj = f"autosub/{self.job_id}/{uuid.uuid4().hex}/{self.inp.stem}.stt.wav"
            uri = f"gs://{args.bucket}/{obj}"
            core.gcs_upload(args.bucket, obj, self.wav)
            try:
                code = args.cloud_language_code or SPEECH_CODES.get(args.source_language, args.source_language)
                core.run([core.sys.executable, "sub.py", "--method", "google", "--input", uri,
                          "--out", str(self.source_tmp), "--lang", code, "--project", args.project,
                          "--source_language", args.source_language, "--timeout_hours", str(args.stt_timeout_hours)],
                         cwd=self.script_dir, timeout_seconds=int(args.stt_timeout_hours * 3600) + 600)
            finally:
                core.gcs_delete(args.bucket, obj)
        else:
            cmd = [core.sys.executable, "sub.py", "--method", "local", "--input", str(self.wav),
                   "--out", str(self.source_tmp), "--source_language", args.source_language,
                   "--model_size", args.whisper_model, "--device", args.device,
                   "--compute_type", args.compute_type, "--hallucination_filter", args.hallucination_filter,
                   "--dedupe_window_seconds", str(args.dedupe_window_seconds)]
            if args.initial_prompt:
                cmd += ["--initial_prompt", args.initial_prompt]
            core.run(cmd, cwd=self.script_dir, timeout_seconds=args.local_stt_timeout_minutes * 60 or None)

    def commit_source(self):
        self.ensure_unchanged()
        if not self.source_tmp.is_file():
            raise RuntimeError("Speech recognition did not create an SRT file")
        has_text = source_ready(self.source_tmp)
        if not has_text and self.source_tmp.read_text(encoding="utf-8-sig").strip():
            raise RuntimeError(f"Speech recognition produced invalid SRT: {self.source_tmp}")
        digest = file_sha256(self.source_tmp)
        self.save(source_pending=dict(sha256=digest, stt_identity=self.stt_key))
        if self.original.exists():
            core.backup_existing(self.original, "backup")
        core.move_replace(self.source_tmp, self.original)
        core.hide_output(self.original)
        self.source_hash = digest if has_text else None
        self.phase = "source_ready" if has_text else "no_text"
        self.save(status=self.phase, stage=self.phase, stt_identity=self.stt_key,
                  source_sha256=self.source_hash, source_attempt=None, source_pending=None, audio=None)
        if not self.args.keep_workspace and self.wav:
            self.wav.unlink(missing_ok=True)
            self.audio_proof.unlink(missing_ok=True)
        if not has_text:
            self.cleanup()

    def begin_translation(self):
        self.start()
        self.ensure_unchanged()
        digest = file_sha256(self.original)
        if self.source_hash is not None and digest != self.source_hash:
            raise RuntimeError("Source subtitles changed before translation")
        self.source_hash = digest
        self.translation_key = translation_identity(self.args, self.source_hash)
        self.render_key = output_identity(self.args, self.source_hash)
        self.checkpoint = self.checkpoint_dir / f"{self.job_id}.{self.translation_key[:24]}.part.json"
        pending = self.state.get("translation_pending", {})
        self.translation_recovered = False
        if not self.args.force and isinstance(pending, dict):
            candidate = Path(pending.get("path", ""))
            if (candidate.parent == self.work_dir and candidate.name.endswith(".translated.srt") and
                    pending.get("translation_identity") == self.translation_key and
                    pending.get("output_identity") == self.render_key and
                    valid_translation(self.original, candidate, self.args.source_language, self.args.output_mode)):
                self.output_tmp = candidate
                self.translation_recovered = True
        if not self.translation_initialized and self.args.force:
            self.checkpoint.unlink(missing_ok=True)
        self.translation_initialized = True
        self.phase = "translating"
        self.save(status="source_ready", stage=self.phase, source_sha256=self.source_hash,
                  stt_identity=self.stt_key, translation_attempt=str(self.output_tmp),
                  translation_pending=dict(path=str(self.output_tmp), translation_identity=self.translation_key,
                                           output_identity=self.render_key))

    def translate(self, runner=None):
        args = self.args
        if file_sha256(self.original) != self.source_hash:
            raise RuntimeError("Source subtitles changed before translation")
        if self.translation_recovered:
            return
        if self.cached is not None:
            render_translations(self.output_tmp, self.original, self.cached,
                                args.source_language, args.target_language, args.output_mode)
        else:
            cmd = [core.sys.executable, "translate.py", "--in", str(self.original), "--out", str(self.output_tmp),
                   *self.translation.cli_arguments(), "--source_language", args.source_language,
                   "--target_language", args.target_language, "--output_mode", args.output_mode,
                   "--checkpoint", str(self.checkpoint), "--batch", str(args.batch), "--sleep", str(args.sleep),
                   "--line_retries", str(args.retries),
                   "--request_timeout_seconds", str(getattr(args, "request_timeout_seconds", 60))]
            (runner or core.run)(cmd, cwd=self.script_dir, timeout_seconds=args.translate_timeout_minutes * 60)

    def finalize(self):
        self.ensure_unchanged()
        if file_sha256(self.original) != self.source_hash:
            raise RuntimeError("Source subtitles changed during translation")
        if not valid_translation(self.original, self.output_tmp, self.args.source_language, self.args.output_mode):
            raise RuntimeError("Translated SRT does not match source timing/content")
        record = dict(path=str(self.output), translation_identity=self.translation_key,
                      output_identity=self.render_key, sha256=file_sha256(self.output_tmp))
        self.save(output_pending=record)
        if self.output.exists():
            core.backup_existing(self.output, "backup")
        core.move_replace(self.output_tmp, self.output)
        core.unhide_output(self.output)
        current = self.store.get(self.inp)
        outputs = current.get("outputs", {})
        outputs = dict(outputs) if isinstance(outputs, dict) else {}
        outputs[str(self.output)] = record
        self.phase = "complete"
        self.save(status="complete", stage="done", outputs=outputs, output=str(self.output),
                  translation_identity=self.translation_key, output_identity=self.render_key,
                  output_pending=None, translation_attempt=None, translation_pending=None, error=None)
        self.cleanup()
        core.Log.success(f"Created: {self.output}")

    def fail(self, error):
        error = redact(error)
        self.phase = "failed"
        self.save(status="failed", stage="error", error=str(error), stt_identity=self.stt_key)
        self.log("file_failed", error=str(error))

    def cleanup(self):
        if self.work_dir and not self.args.keep_workspace:
            core.cleanup_workspace(self.inp, self.work_dir)
