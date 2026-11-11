"""Download a public Whisper model and exercise local STT without API credentials."""
import gc
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODEL_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="autosub-model-smoke-") as temporary:
        root = Path(temporary)
        # Set before importing huggingface_hub; the test uses a fresh public cache.
        os.environ["HF_HOME"] = str(root / "hf")
        os.environ["HF_XET_CACHE"] = str(root / "xet")
        os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
        os.environ.pop("HF_HUB_DISABLE_XET", None)

        from faster_whisper.utils import download_model
        from huggingface_hub import file_download
        from srt_utils import read_srt
        from stt_engine import load_model, transcribe_one

        cache = root / "hf" / "hub"
        with patch.object(file_download, "xet_get", wraps=file_download.xet_get) as xet:
            model_dir = download_model("tiny", cache_dir=str(cache),
                                       revision=MODEL_REVISION, use_auth_token=False)
        if not xet.called:
            raise RuntimeError("Public model download did not use hf-xet")

        with patch.object(file_download, "xet_get", side_effect=RuntimeError("Unexpected network download")):
            cached = download_model("tiny", cache_dir=str(cache), revision=MODEL_REVISION,
                                    local_files_only=True, use_auth_token=False)
        if Path(cached) != Path(model_dir):
            raise RuntimeError("Local cache did not return the downloaded model")

        config = {"model_size": model_dir, "device": "auto", "compute_type": "float16",
                  "source_language": "en", "hallucination_filter": "off"}
        model = load_model(config)
        try:
            if model.model.device == "cpu" and not model.model.compute_type.startswith("int8"):
                raise RuntimeError(f"Automatic CPU selection returned {model.model.compute_type}, not int8")
            output = root / "demo.srt"
            summary = transcribe_one(model, ROOT / "examples" / "demo.en.wav", output, config)
            blocks = read_srt(output)
            text = " ".join(block[3] for block in blocks).lower()
            if (summary["language"] != "en" or summary["segments"] != len(blocks)
                    or "hello" not in text or "test" not in text):
                raise RuntimeError("The public audio did not produce the expected English subtitles")
            print(f"PASS: hf-xet download and cache; {model.model.device} "
                  f"{model.model.compute_type} tiny transcription produced {len(blocks)} subtitles")
        finally:
            del model
            gc.collect()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Signed download URLs can contain temporary tokens; do not print them.
        message = re.sub(r"https?://\S+", "<URL>", str(exc))
        print(f"Model smoke test failed ({type(exc).__name__}): {message[:400]}", file=sys.stderr)
        raise SystemExit(1) from None
