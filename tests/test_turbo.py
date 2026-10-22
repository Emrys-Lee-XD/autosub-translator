"""Behavioral concurrency/recovery checks without GPU or network dependencies."""
import contextlib
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import gemini
import gui_support
import main
import stt_worker
import stt_engine
from pipeline_job import PipelineJob, valid_audio
from process_utils import OwnedProcess, StageError, run_captured
from srt_utils import read_srt
from task_state import StateStore
from turbo_scheduler import TurboScheduler
from tests.test_multilang import options, SRT, fixture_audio


class FakeWorker:
    instances = []
    calls = []
    hook = None

    def __init__(self, script_dir, config, post):
        self.generation = uuid.uuid4().hex
        self.ready = False
        self.started = time.monotonic()
        self.post = post
        self.closed = False
        type(self).instances.append(self)
        self.post(dict(kind="stt", event="worker_ready", generation=self.generation,
                       load_seconds=0, device="fake-cuda"))

    def transcribe(self, job):
        type(self).calls.append(job.inp.name)
        if type(self).hook:
            type(self).hook(self, job)
        else:
            self.complete(job)

    def complete(self, job):
        job.source_tmp.write_text(SRT, encoding="utf-8")
        self.post(dict(kind="stt", event="job_completed", generation=self.generation,
                       job_id=job.job_id, attempt=job.attempt, seconds=0.01, summary={}))

    def close(self, graceful=True):
        self.closed = True


def fake_runner(command, **kwargs):
    if command[1] == "ffmpeg_only.py":
        folder = Path(command[command.index("--out_dir") + 1])
        fixture_audio(folder / f"{Path(command[2]).stem}.stt.wav")
    elif command[1] == "translate.py":
        source = Path(command[command.index("--in") + 1])
        output = Path(command[command.index("--out") + 1])
        mode = command[command.index("--output_mode") + 1]
        gemini.write_translated_srt(output, read_srt(source), ["Translated"], "en", "zh-CN", mode)
    else:
        raise AssertionError(command)


class TurboTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"})
        self.env.start()
        FakeWorker.instances, FakeWorker.calls, FakeWorker.hook = [], [], None

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def videos(self, count=3):
        paths = [self.root / f"{i:02d}.mp4" for i in range(count)]
        for path in paths:
            path.write_bytes(b"synthetic-video")
        return paths

    def scheduler(self, paths, runner=fake_runner, **overrides):
        opts = options(**dict(turbo=True, audio_prefetch=2, gui_events=True, stop_file=None) | overrides)
        return TurboScheduler(paths, opts, ROOT, self.root / "state.json", None,
                              self.root / "checkpoints", worker_factory=FakeWorker, runner=runner)

    def run_quiet(self, scheduler):
        with contextlib.redirect_stdout(io.StringIO()):
            return scheduler.run()

    def test_translation_backlog_does_not_block_stt_and_single_model(self):
        translated = threading.Event()
        third_stt = threading.Event()
        overlap = []
        def hook(worker, job):
            if len(FakeWorker.calls) == 3:
                third_stt.set()
            worker.complete(job)
        FakeWorker.hook = hook
        def runner(command, **kwargs):
            if command[1] == "translate.py" and not translated.is_set():
                overlap.append(third_stt.wait(timeout=5))
                translated.set()
            fake_runner(command, **kwargs)
        scheduler = self.scheduler(self.videos(), runner)
        self.assertEqual(self.run_quiet(scheduler), 0)
        self.assertEqual(overlap, [True])
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertTrue(FakeWorker.instances[0].closed)
        self.assertEqual(scheduler.recognized, 3)
        records = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records), 3)
        self.assertTrue(all(row["status"] == "complete" for row in records.values()))
        self.assertFalse(list(self.root.rglob("*.stt.wav")))

    def test_audio_prefetch_includes_extraction_and_is_bounded(self):
        blocked = []
        seen_ahead = []
        def hook(worker, job):
            if not blocked:
                blocked.append((worker, job))
            else:
                worker.complete(job)
        FakeWorker.hook = hook
        released = False
        def gui_event(args, event, **data):
            nonlocal released
            if event == "turbo_status":
                seen_ahead.append(data["audio_ahead"])
                if data["audio_ahead"] == 2 and blocked and not released:
                    released = True
                    blocked[0][0].complete(blocked[0][1])
        scheduler = self.scheduler(self.videos(5))
        with patch.object(main, "gui_event", side_effect=gui_event):
            self.assertEqual(self.run_quiet(scheduler), 0)
        self.assertTrue(released)
        self.assertLessEqual(max(seen_ahead), 2)

    def test_recovered_audio_obeys_the_same_prefetch_limit(self):
        paths = self.videos(5)
        store = StateStore(self.root / "state.json")
        for inp in paths:
            job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
            job.begin_extract()
            job.extract(fake_runner)
            job.commit_audio()
        scheduler = self.scheduler(paths)
        # Hold model initialization while the scheduler restores audio records.
        def loading_worker(script_dir, config, post):
            worker = FakeWorker(script_dir, config, lambda data: None)
            worker.post = post
            return worker
        scheduler.worker_factory = loading_worker
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as extract, ThreadPoolExecutor(1) as translate:
            scheduler._dispatch(extract, translate)
            self.assertLessEqual(sum(job.phase in {"audio_ready", "extracting"} for job in scheduler.jobs), 2)
            scheduler.worker.close()

    def test_cached_model_load_avoids_network_and_only_cache_miss_downloads(self):
        from huggingface_hub.errors import LocalEntryNotFoundError
        config = dict(model_size="large-v3", device="cuda", compute_type="float16")
        model = object()
        cached = self.root / "model"
        cached.mkdir()
        for part in ("model.bin", "config.json", "tokenizer.json"):
            (cached / part).write_bytes(b"fixture")
        with patch("faster_whisper.utils.download_model", return_value=str(cached)), patch("faster_whisper.WhisperModel", return_value=model) as loader:
            self.assertIs(stt_engine.load_model(config), model)
            self.assertEqual(loader.call_args.args[0], str(cached))
            self.assertEqual(loader.call_count, 1)
        with patch("faster_whisper.utils.download_model", side_effect=LocalEntryNotFoundError("missing")), patch("faster_whisper.WhisperModel", return_value=model) as loader:
            self.assertIs(stt_engine.load_model(config), model)
            self.assertEqual(loader.call_args.args[0], "large-v3")
            self.assertEqual(loader.call_count, 1)
        (cached / "model.bin").unlink()
        with patch("faster_whisper.utils.download_model", return_value=str(cached)), patch("faster_whisper.WhisperModel", return_value=model) as loader:
            self.assertIs(stt_engine.load_model(config), model)
            self.assertEqual(loader.call_args.args[0], "large-v3")
        with patch("faster_whisper.utils.download_model", side_effect=LocalEntryNotFoundError("missing")), patch("faster_whisper.WhisperModel", side_effect=ValueError("Invalid model")) as loader:
            with self.assertRaises(ValueError):
                stt_engine.load_model(config)
            self.assertEqual(loader.call_count, 1)

    def test_safe_stop_preserves_stt_and_resume_does_not_repeat_it(self):
        paths = self.videos(3)
        stop = self.root / "stop"
        def hook(worker, job):
            stop.touch()
            worker.complete(job)
        FakeWorker.hook = hook
        scheduler = self.scheduler(paths, stop_file=stop)
        self.assertEqual(self.run_quiet(scheduler), 130)
        self.assertEqual(FakeWorker.calls, [paths[0].name])
        self.assertEqual(scheduler.jobs[0].phase, "source_ready")
        self.assertFalse(scheduler.jobs[0].output.exists())
        stop.unlink()
        FakeWorker.hook = None
        self.assertEqual(self.run_quiet(self.scheduler(paths)), 0)
        self.assertEqual(FakeWorker.calls.count(paths[0].name), 1)

    def test_worker_crash_retries_file_once_and_rejects_stale_events(self):
        crashes = []
        def hook(worker, job):
            if not crashes:
                crashes.append(worker)
                worker.post(dict(kind="stt", event="worker_exit", generation=worker.generation))
            else:
                crashes[0].post(dict(kind="stt", event="job_completed", generation=crashes[0].generation,
                                     job_id=job.job_id, attempt="stale", seconds=0, summary={}))
                worker.complete(job)
        FakeWorker.hook = hook
        scheduler = self.scheduler(self.videos(2))
        self.assertEqual(self.run_quiet(scheduler), 0)
        self.assertEqual(len(FakeWorker.instances), 2)
        self.assertEqual(scheduler.restarts, 1)
        self.assertEqual(FakeWorker.calls.count("00.mp4"), 2)

    def test_repeated_crashes_have_a_batch_restart_limit(self):
        def hook(worker, job):
            worker.post(dict(kind="stt", event="worker_exit", generation=worker.generation))
        FakeWorker.hook = hook
        scheduler = self.scheduler(self.videos(5))
        self.assertEqual(self.run_quiet(scheduler), 1)
        self.assertEqual(len(FakeWorker.instances), 3)
        self.assertTrue(all(item.closed for item in FakeWorker.instances))
        self.assertIsNotNone(scheduler.stt_blocked)

    def test_auth_error_pauses_translation_but_stt_finishes(self):
        calls = []
        def runner(command, **kwargs):
            if command[1] == "translate.py":
                calls.append(command)
                raise StageError("Invalid key", code=401)
            fake_runner(command, **kwargs)
        scheduler = self.scheduler(self.videos(4), runner)
        self.assertEqual(self.run_quiet(scheduler), 1)
        self.assertEqual(scheduler.recognized, 4)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(job.phase == "source_ready" for job in scheduler.jobs), 3)

    def test_disk_pause_does_not_spin_or_load_new_files_forever(self):
        scheduler = self.scheduler(self.videos())
        with patch("turbo_scheduler.shutil.disk_usage", return_value=type("Disk", (), {"free": 1})()):
            self.assertEqual(self.run_quiet(scheduler), 1)
        self.assertIsNotNone(scheduler.extract_blocked)
        self.assertFalse(FakeWorker.calls)

    def test_srt_only_and_verified_outputs_do_not_start_model(self):
        source = self.root / "a.srt"
        source.write_text(SRT, encoding="utf-8")
        self.assertEqual(self.run_quiet(self.scheduler([source])), 0)
        self.assertEqual(self.run_quiet(self.scheduler([source])), 0)
        self.assertFalse(FakeWorker.instances)

    def test_source_tmp_written_before_crash_is_recovered(self):
        inp = self.videos(1)[0]
        store = StateStore(self.root / "state.json")
        job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text(SRT, encoding="utf-8")
        recovered = PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        recovered.start()
        self.assertEqual(recovered.phase, "source_ready")
        self.assertTrue(recovered.original.exists())
        self.assertFalse(recovered.wav.exists())

    def test_audio_recovery_requires_success_proof_before_state_commit(self):
        inp = self.videos(1)[0]
        store = StateStore(self.root / "state.json")
        job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
        job.begin_extract()
        fixture_audio(job.wav)  # A valid WAV can still be output of failed FFmpeg.
        recovered = PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        recovered.start()
        self.assertEqual(recovered.phase, "pending")
        recovered.begin_extract()
        recovered.extract(fake_runner)  # Success proof saved; state commit interrupted.
        second = PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        second.start()
        self.assertEqual(second.phase, "audio_ready")

    def test_source_commit_interrupted_after_rename_is_recovered(self):
        inp = self.videos(1)[0]
        store = StateStore(self.root / "state.json")
        job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text(SRT, encoding="utf-8")
        original_update = store.update
        def fail_final(source, **fields):
            if "source_sha256" in fields:
                raise OSError("Simulated interrupted state save")
            return original_update(source, **fields)
        with patch.object(store, "update", side_effect=fail_final), self.assertRaises(OSError):
            job.commit_source()
        recovered = PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        self.assertEqual(recovered.phase, "source_ready")
        recovered.start()
        self.assertFalse(recovered.wav.exists())
        self.assertIsNone(recovered.state.get("source_pending"))

    def test_empty_source_commit_interrupted_after_rename_is_recovered(self):
        inp = self.videos(1)[0]
        store = StateStore(self.root / "state.json")
        job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text("", encoding="utf-8")
        update = store.update
        def fail_final(source, **fields):
            if "source_sha256" in fields:
                raise OSError("Simulated interrupted state save")
            return update(source, **fields)
        with patch.object(store, "update", side_effect=fail_final), self.assertRaises(OSError):
            job.commit_source()
        recovered = PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        self.assertEqual(recovered.phase, "no_text")
        self.assertEqual(recovered.state["status"], "no_text")

    def test_no_text_cache_does_not_hide_externally_changed_source(self):
        inp = self.videos(1)[0]
        store = StateStore(self.root / "state.json")
        job = PipelineJob(inp, options(), ROOT, store, self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text("", encoding="utf-8")
        job.commit_source()
        main.unhide_output(job.original)
        job.original.write_text(SRT, encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unknown provenance"):
            PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        job.original.write_text("invalid subtitle", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            PipelineJob(inp, options(), ROOT, StateStore(store.path), self.root / "checkpoints")

    def test_output_commit_interrupted_after_rename_is_reconciled(self):
        source = self.root / "a.srt"
        source.write_text(SRT, encoding="utf-8")
        store = StateStore(self.root / "state.json")
        job = PipelineJob(source, options(), ROOT, store, self.root / "checkpoints")
        job.begin_translation()
        job.translate(fake_runner)
        update = store.update
        def fail_final(source, **fields):
            if fields.get("status") == "complete":
                raise OSError("Simulated interrupted state save")
            return update(source, **fields)
        with patch.object(store, "update", side_effect=fail_final), self.assertRaises(OSError):
            job.finalize()
        recovered = PipelineJob(source, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        self.assertEqual(recovered.phase, "complete")
        self.assertEqual(recovered.state["status"], "complete")
        self.assertIsNone(recovered.state["output_pending"])
        self.assertIsNone(recovered.state["translation_pending"])

    def test_source_changed_before_translation_is_rejected(self):
        inp = self.videos(1)[0]
        job = PipelineJob(inp, options(), ROOT, StateStore(self.root / "state.json"), self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text(SRT, encoding="utf-8")
        job.commit_source()
        main.unhide_output(job.original)
        job.original.write_text(SRT.replace("Hello world", "Changed"), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            job.begin_translation()
        self.assertFalse(job.output.exists())

    def test_worker_startup_failure_pauses_without_retries(self):
        scheduler = self.scheduler(self.videos())
        scheduler.worker_factory = lambda *args: (_ for _ in ()).throw(OSError("GPU process cannot start"))
        self.assertEqual(self.run_quiet(scheduler), 1)
        self.assertIsNotNone(scheduler.stt_blocked)
        self.assertEqual(scheduler.restarts, 0)
        self.assertFalse(FakeWorker.calls)

    def test_owned_process_closes_descendant_as_well_as_direct_child(self):
        pid_file = self.root / "pid"
        code = ("import subprocess,sys,time; from pathlib import Path; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)")
        child = OwnedProcess([sys.executable, "-c", code, str(pid_file)], ROOT)
        try:
            until = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < until:
                time.sleep(0.01)
            self.assertTrue(pid_file.exists())
            pid = int(pid_file.read_text())
        finally:
            child.close()
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                try:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
                finally:
                    kernel.CloseHandle(handle)
        else:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_translation_tmp_recovered_without_another_api_request(self):
        source = self.root / "a.srt"
        source.write_text(SRT, encoding="utf-8")
        store = StateStore(self.root / "state.json")
        job = PipelineJob(source, options(), ROOT, store, self.root / "checkpoints")
        job.begin_translation()
        job.translate(fake_runner)
        recovered = PipelineJob(source, options(), ROOT, StateStore(store.path), self.root / "checkpoints")
        recovered.begin_translation()
        with patch.object(main, "run") as runner:
            recovered.translate()
            runner.assert_not_called()
        recovered.finalize()
        self.assertTrue(recovered.output.exists())

    def test_input_changed_during_stt_does_not_overwrite_source(self):
        inp = self.videos(1)[0]
        job = PipelineJob(inp, options(), ROOT, StateStore(self.root / "state.json"), self.root / "checkpoints")
        job.begin_extract()
        job.extract(fake_runner)
        job.commit_audio()
        job.begin_stt()
        job.source_tmp.write_text(SRT, encoding="utf-8")
        inp.write_bytes(b"replacement-input")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            job.commit_source()
        self.assertFalse(job.original.exists())

    def test_state_store_rejects_worker_thread_writes(self):
        store = StateStore(self.root / "state.json")
        errors = []
        def write():
            try:
                store.update(self.root / "a", status="complete")
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=write)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertFalse(store.path.exists())

    def test_config_round_trip_and_gui_overrides_turbo(self):
        config = self.root / "config.json"
        values = {**gui_support.DEFAULTS, "turbo": True, "audio_prefetch": "3"}
        gui_support.save_settings(values, config)
        self.assertTrue(gui_support.load_settings(config)["turbo"])
        source = self.videos(1)[0]
        command, _ = gui_support.build_command({"input": str(source), "turbo": False}, dry_run=True)
        self.assertIn("--no_turbo", command)
        with self.assertRaises(ValueError):
            gui_support.build_command({"input": str(source), "turbo": True, "audio_prefetch": "5"})
        result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(source), "--config", str(config),
                                 "--no_turbo", "--dry_run"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.root.glob(".autosub*")), [])

    def test_worker_loop_reuses_model_and_emits_protocol_only(self):
        commands = queue.Queue()
        config = dict(model_size="fake", device="cpu", compute_type="int8")
        commands.put(dict(protocol=1, generation="test", command="initialize", config=config))
        for index in range(3):
            commands.put(dict(protocol=1, generation="test", command="transcribe", job_id=str(index),
                              attempt=str(index), config=config, audio="fake", output="fake"))
        commands.put(dict(protocol=1, generation="test", command="shutdown"))
        model = object()
        models = []
        def transcriber(loaded, *args):
            print("This log must not corrupt stdout")
            models.append(loaded)
            return {}
        output = io.StringIO()
        with patch("sys.stderr", io.StringIO()):
            stt_worker.serve(lambda config: model, transcriber, commands, output)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(sum(row["event"] == "worker_ready" for row in events), 1)
        self.assertEqual(sum(row["event"] == "job_completed" for row in events), 3)
        self.assertEqual(models, [model] * 3)

    def test_real_worker_pipe_initializes_native_libraries_before_reader(self):
        code = """import stt_worker
def load(config):
    import numpy
    return object()
def transcribe(*args):
    return {'segments': 0}
stt_worker.serve(load, transcribe)
"""
        owned = OwnedProcess([sys.executable, "-u", "-c", code], ROOT,
                             stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        events = queue.Queue()
        def read():
            for line in owned.process.stdout:
                events.put(json.loads(line))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def send(command, **kw):
            owned.process.stdin.write(json.dumps(dict(protocol=1, generation="pipe", command=command, **kw)) + "\n")
            owned.process.stdin.flush()
        try:
            send("initialize", config=dict(device="cpu"))
            self.assertEqual(events.get(timeout=15)["event"], "worker_ready")
            for index in range(2):
                send("transcribe", job_id=str(index), attempt=str(index), config={}, audio="fake", output="fake")
                self.assertEqual(events.get(timeout=5)["event"], "job_started")
                self.assertEqual(events.get(timeout=5)["event"], "job_completed")
            send("shutdown")
            self.assertEqual(owned.process.wait(timeout=5), 0)
        finally:
            owned.close()
            reader.join(timeout=5)

    def test_owned_child_and_timeout_release_process(self):
        child = OwnedProcess([sys.executable, "-c", "import time; time.sleep(60)"], ROOT)
        child.close()
        self.assertIsNotNone(child.process.poll())
        with self.assertRaisesRegex(StageError, "timed out"):
            run_captured([sys.executable, "-c", "import time; time.sleep(60)"], ROOT, timeout_seconds=0.05)

    def test_audio_validation_rejects_truncation(self):
        path = self.root / "audio.wav"
        fixture_audio(path)
        self.assertTrue(valid_audio(path))
        path.write_bytes(path.read_bytes()[:-100])
        self.assertFalse(valid_audio(path))


if __name__ == "__main__":
    unittest.main()
