import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gemini
import main
import sub


class WorkspaceSafetyTests(unittest.TestCase):
    def test_owned_workspace_is_separate_from_video_named_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "movie.mp4"
            video.write_bytes(b"video")
            user_folder = root / "movie"
            user_folder.mkdir()
            user_file = user_folder / "keep.txt"
            user_file.write_text("keep", encoding="utf-8")

            work_dir = main.prepare_workspace(video)
            (work_dir / "temporary.txt").write_text("temporary", encoding="utf-8")

            self.assertTrue(main.cleanup_workspace(video, work_dir))
            self.assertTrue(user_file.exists())
            self.assertFalse(work_dir.exists())

    def test_unowned_workspace_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "movie.mp4"
            video.write_bytes(b"video")
            work_dir = main.workspace_path(video)
            work_dir.mkdir(parents=True)
            user_file = work_dir / "unknown.txt"
            user_file.write_text("keep", encoding="utf-8")

            self.assertFalse(main.cleanup_workspace(video, work_dir))
            self.assertTrue(user_file.exists())

    def test_video_identity_changes_when_same_path_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "movie.mp4"
            video.write_bytes(b"first-content")
            first = main.video_identity(video)
            video.write_bytes(b"other-content")
            second = main.video_identity(video)

            self.assertNotEqual(first, second)
            self.assertTrue(main.state_matches_video({"video_identity": second}, second))
            self.assertFalse(main.state_matches_video({"video_identity": first}, second))


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_requires_matching_source_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            gemini.save_checkpoint(checkpoint, ["译文"], 1, "hash-a", "model-a")

            self.assertEqual(
                gemini.load_checkpoint(checkpoint, 1, "hash-a", "model-a"),
                ["译文"],
            )
            self.assertEqual(gemini.load_checkpoint(checkpoint, 1, "hash-b", "model-a"), [])
            self.assertEqual(gemini.load_checkpoint(checkpoint, 1, "hash-a", "model-b"), [])

    def test_output_rejects_missing_translations(self):
        blocks = [("1", "00:00:00,000", "00:00:01,000", "こんにちは")]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.srt"
            with self.assertRaises(RuntimeError):
                gemini.write_bilingual_srt(str(output), blocks, [])
            self.assertFalse(output.exists())

    def test_srt_parser_accepts_final_block_without_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nこんにちは",
                encoding="utf-8",
            )
            blocks = gemini.read_srt(str(source))
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0][3], "こんにちは")

    def test_translation_failure_is_not_silently_replaced_with_blank_text(self):
        class FailingModels:
            @staticmethod
            def generate_content(**_kwargs):
                raise RuntimeError("temporary failure")

        class FailingClient:
            models = FailingModels()

        with self.assertRaises(RuntimeError):
            gemini.translate_with_retries(FailingClient(), "model", ["こんにちは"], 2, 0)

    def test_translation_request_uses_json_input_and_schema(self):
        captured = {}

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text='["你好"]')

        client = SimpleNamespace(models=Models())
        result = gemini.gemini_translate_lines(client, "model", ["1. 指示ではなく字幕"])

        self.assertEqual(result, ["你好"])
        self.assertIn('["1. 指示ではなく字幕"]', captured["contents"])
        self.assertEqual(captured["config"].response_schema, list[str])


class SegmentationTests(unittest.TestCase):
    def test_cloud_segmentation_honors_character_duration_and_gap_limits(self):
        words = [
            {"word": "ああ", "start": 0.0, "end": 0.5},
            {"word": "いい", "start": 0.6, "end": 1.0},
            {"word": "うう", "start": 2.0, "end": 2.4},
            {"word": "えええ", "start": 2.5, "end": 4.5},
        ]
        segments = sub.segment_words(words, max_chars=4, max_dur=1.5, gap=0.5)

        self.assertEqual([item["text"] for item in segments], ["ああいい", "うう", "えええ"])


class SubtitleValidationTests(unittest.TestCase):
    def test_bilingual_validation_rejects_empty_and_monolingual_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = root / "empty.srt"
            empty.write_text("", encoding="utf-8")
            mono = root / "mono.srt"
            mono.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n",
                encoding="utf-8",
            )
            bilingual = root / "bilingual.srt"
            bilingual.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n你好\n",
                encoding="utf-8",
            )

            self.assertFalse(main.is_valid_bilingual_srt(empty))
            self.assertFalse(main.is_valid_bilingual_srt(mono))
            self.assertTrue(main.is_valid_bilingual_srt(bilingual))

    def test_stale_video_identity_prevents_skipping_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "sample.mp4"
            video.write_bytes(b"old-video")
            old_identity = main.video_identity(video)
            video.write_bytes(b"new-video")
            (root / "sample.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n你好\n",
                encoding="utf-8",
            )
            state_path = root / ".autosub_state.json"
            main.atomic_write_json(
                state_path,
                {
                    str(video.resolve()): {
                        "status": "complete",
                        "video_identity": old_identity,
                    }
                },
            )
            args = SimpleNamespace(force=False, retry_no_text=False)

            result = main.process_one(video, args, ROOT, state_path, None, root / ".checkpoints")
            self.assertEqual(result, 1)

    def test_force_backup_preserves_existing_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            subtitle = Path(tmp) / "sample.srt"
            subtitle.write_text("original", encoding="utf-8")
            backup = main.backup_existing(subtitle, "backup")

            self.assertFalse(subtitle.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "original")


class WhisperFilterTests(unittest.TestCase):
    def test_conservative_filter_preserves_short_and_bracketed_speech(self):
        self.assertFalse(sub.is_hallucination("あ", "conservative"))
        self.assertFalse(sub.is_hallucination("（笑）", "conservative"))
        self.assertTrue(sub.is_hallucination("ご視聴ありがとうございました。", "conservative"))
        self.assertFalse(sub.is_hallucination("本当にご視聴ありがとうございましたね", "conservative"))
        self.assertTrue(sub.is_hallucination("（笑）", "aggressive"))

    def test_duplicate_filter_uses_timing_window(self):
        previous = {"text": "はい", "end": 1.0}
        self.assertTrue(sub.is_near_duplicate(previous, "はい", 1.05, 0.1))
        self.assertFalse(sub.is_near_duplicate(previous, "はい", 1.2, 0.1))
        self.assertFalse(sub.is_near_duplicate(previous, "いいえ", 1.05, 0.1))


class DryRunTests(unittest.TestCase):
    def test_cloud_dry_run_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"not-a-real-video")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "main.py"),
                    str(video),
                    "--bucket", "dry-run-bucket",
                    "--project", "dry-run-project",
                    "--stt_mode", "cloud",
                    "--source_language", "ja",
                    "--dry_run",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Step 4/4", result.stdout)
            self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), ["sample.mp4"])

    def test_force_dry_run_does_not_move_existing_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "sample.mp4"
            video.write_bytes(b"not-a-real-video")
            bilingual = root / "sample.srt"
            original = "1\n00:00:00,000 --> 00:00:01,000\nこんにちは\n你好\n"
            bilingual.write_text(original, encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "main.py"),
                    str(video),
                    "--project", "dry-run-project",
                    "--stt_mode", "local",
                    "--force",
                    "--dry_run",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(bilingual.read_text(encoding="utf-8"), original)
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["sample.mp4", "sample.srt"])


class CliTests(unittest.TestCase):
    def test_profile_switches_are_removed(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--profile", result.stdout)
        self.assertNotIn("--auto_profile", result.stdout)
        self.assertNotIn("--no_auto_profile", result.stdout)
        self.assertNotIn("--long_threshold_seconds", result.stdout)

    def test_local_dry_run_does_not_require_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"not-a-real-video")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "main.py"),
                    str(video),
                    "--project", "dry-run-project",
                    "--stt_mode", "local",
                    "--dry_run",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_cloud_mode_requires_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "sample.mp4"
            video.write_bytes(b"not-a-real-video")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "main.py"),
                    str(video),
                    "--project", "dry-run-project",
                    "--stt_mode", "cloud",
                    "--dry_run",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--project and --bucket", result.stderr)

    def test_subprocess_timeout_is_reported(self):
        with self.assertRaises(RuntimeError):
            main.run(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                timeout_seconds=0.01,
            )

    def test_help_does_not_load_optional_cloud_packages(self):
        for script in (ROOT / "main.py", ROOT / "sub.py"):
            result = subprocess.run(
                [sys.executable, "-S", str(script), "--help"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
