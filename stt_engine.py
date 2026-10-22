"""One model lifetime, many independent transcriptions. No process exits here."""
import gc
import time


def load_model(config):
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    from pathlib import Path
    options = dict(device=config["device"], compute_type=config["compute_type"])
    # A complete cached model should not wait on Hugging Face network checks.
    # Missing/incomplete caches retain the ordinary first-download behavior.
    from huggingface_hub.errors import LocalEntryNotFoundError
    name = config["model_size"]
    if not Path(name).is_dir():
        try:
            cached = Path(download_model(name, local_files_only=True))
        except LocalEntryNotFoundError:
            cached = None
        if cached and all((cached / part).is_file() for part in ("model.bin", "config.json", "tokenizer.json")):
            name = str(cached)
    return WhisperModel(name, **options)


def transcribe_one(model, audio_path, out_path, config, progress=None):
    # Import only formatting/filtering helpers; sub.py imports this engine lazily.
    from sub import is_hallucination, is_near_duplicate, write_srt
    options = dict(vad_filter=True, vad_parameters=dict(
        threshold=0.3, min_speech_duration_ms=200,
        min_silence_duration_ms=500, speech_pad_ms=800),
        beam_size=5, word_timestamps=False, condition_on_previous_text=False)
    language = config.get("source_language", "auto")
    if language != "auto":
        options["language"] = language.split("-", 1)[0]
    if config.get("initial_prompt"):
        options["initial_prompt"] = config["initial_prompt"]
    segments, info = model.transcribe(str(audio_path), **options)
    results = []
    hallucinations = duplicates = 0
    reported = 0.0
    for index, segment in enumerate(segments):
        text = segment.text.strip()
        if is_hallucination(text, config.get("hallucination_filter", "off")):
            hallucinations += 1
            continue
        if results and is_near_duplicate(results[-1], text, segment.start,
                                        config.get("dedupe_window_seconds", 0.1)):
            duplicates += 1
            continue
        results.append(dict(start=segment.start, end=segment.end, text=text))
        now = time.monotonic()
        if progress and now - reported >= 0.5:
            progress(dict(seconds=segment.end, duration=info.duration,
                          segments=len(results), language=info.language))
            reported = now
        if index % 50 == 0:
            gc.collect()
    # Exhaust the generator and atomically write SRT before declaring success.
    write_srt(results, str(out_path))
    summary = dict(segments=len(results), language=info.language,
                   duration=info.duration, hallucinations=hallucinations,
                   duplicates=duplicates)
    del segments, results
    gc.collect()
    return summary
