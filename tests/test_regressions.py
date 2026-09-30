import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main
import gemini
import sub

MONO = "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n"
BI = MONO + "你好\n"


class RegressionTests(unittest.TestCase):
    def test_translation_must_preserve_source_text_timing_and_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "source.srt", Path(tmp) / "output.srt"
            source.write_text(MONO, encoding="utf-8")
            output.write_text(BI, encoding="utf-8")
            self.assertTrue(main.translation_matches_source(source, output))
            for text in (BI.replace("こんにちは", "wrong"), BI.replace("00:00:01,000", "00:00:02,000"),
                         BI + "\n2\n00:00:02,000 --> 00:00:03,000\nextra\n多余\n"):
                output.write_text(text, encoding="utf-8")
                self.assertFalse(main.translation_matches_source(source, output))

    def test_parser_rejects_invalid_tail_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.srt"
            for text in (BI + "\n2\nbroken", BI.replace("00:00:01,000", "00:99:01,000"),
                         BI.replace("00:00:01,000", "00:00:00,000"),
                         "garbage\n\n" + BI, BI + "\n" + BI):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    self.assertFalse(main.is_valid_bilingual_srt(path))
                    with self.assertRaises(ValueError):
                        gemini.read_srt(path)

    def test_checkpoint_rejects_blank_nonstring_and_excess_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            for items in ([""], [None], [123], ["a", "b"]):
                gemini.save_checkpoint(path, items, 1, "hash", "model")
                self.assertEqual(gemini.load_checkpoint(path, 1, "hash", "model"), [])

    def test_blank_translation_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.srt"
            path.write_text("original", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                gemini.write_bilingual_srt(path, [("1", "00:00:00,000", "00:00:01,000", "hi")], [" "])
            self.assertEqual(path.read_text(), "original")

    def test_replacement_failure_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "new.srt", Path(tmp) / "old.srt"
            source.write_text("new")
            target.write_text("old")
            with patch.object(main.os, "replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    main.move_replace(source, target)
            self.assertEqual(source.read_text(), "new")
            self.assertEqual(target.read_text(), "old")

    def test_changed_video_uses_new_workspace_and_preserves_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "movie.mp4"
            video.write_bytes(b"old")
            old = main.prepare_workspace(video)
            audio = old / "movie.stt.wav"
            audio.write_bytes(b"old-audio")
            video.write_bytes(b"new-video")
            new = main.prepare_workspace(video)
            self.assertNotEqual(new, old)
            self.assertTrue(main.cleanup_workspace(video, new))
            self.assertEqual(audio.read_bytes(), b"old-audio")

    def test_stt_failure_is_not_masked_by_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "old.srt"
            output.write_text(MONO, encoding="utf-8")
            with patch.object(main, "run", side_effect=RuntimeError("failed")):
                with self.assertRaises(RuntimeError):
                    main.call_sub_py(ROOT, "local", "audio.wav", output, 0, "model", "cpu", "int8", "off", 0, "", 0, False)

    def test_all_float_arguments_reject_nonfinite_values(self):
        for validator in (main.positive_float, main.non_negative_float, gemini.non_negative_float,
                          sub.positive_float, sub.non_negative_float):
            for value in ("nan", "inf", "-inf"):
                with self.subTest(validator=validator, value=value):
                    with self.assertRaises(argparse.ArgumentTypeError):
                        validator(value)

    def test_distinct_video_stems_have_distinct_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("movie.mp4", "movie_ja.mp4"):
                (root / name).write_bytes(b"video")
            result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(root),
                                     "--stt_mode", "local", "--dry_run"],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("movie.zh-CN.bilingual.srt", result.stdout)
            self.assertIn("movie_ja.zh-CN.bilingual.srt", result.stdout)
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_dry_run_reads_stale_state_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "movie.mp4"
            video.write_bytes(b"old")
            identity = main.video_identity(video)
            video.write_bytes(b"new-video")
            (root / "movie.zh-CN.bilingual.srt").write_text(BI, encoding="utf-8")
            state = root / ".autosub_state.json"
            state.write_text(json.dumps({str(video.resolve()): {"video_identity": identity}}))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(video),
                                     "--project", "test", "--stt_mode", "local", "--dry_run"],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_existing_japanese_skips_audio_and_stt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "movie.mp4"
            video.write_bytes(b"video")
            (root / "movie_ja.srt").write_text(MONO, encoding="utf-8")
            args = SimpleNamespace(force=False, retry_no_text=False, dry_run=False,
                stt_mode="local", device="cpu", model="model", project="test", location="global",
                batch=20, sleep=0, translate_timeout_minutes=1, retries=1, keep_workspace=False,
                always_cleanup=False)
            def translate(_root, _input, output, *unused):
                output.write_text(BI, encoding="utf-8")
            with patch.object(main, "run") as run, patch.object(main, "call_sub_py") as stt, \
                 patch.object(main, "ffprobe_duration_seconds", return_value=None), \
                 patch.object(main, "call_gemini_py", side_effect=translate):
                result = main.process_one(video, args, ROOT, None, None, root / "checkpoints")
            self.assertEqual(result, 0)
            run.assert_not_called()
            stt.assert_not_called()
            self.assertEqual((root / "movie.srt").read_text(encoding="utf-8"), BI)


if __name__ == "__main__":
    unittest.main()
