"""Bounded audio prefetch, one resident STT worker, independent translation."""
import queue
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import main as core
from pipeline_job import PipelineJob
from process_utils import StageError, run_captured
from stt_client import SttClient
from task_state import StateStore
from translation_config import redact

TERMINAL = {"complete", "no_text", "failed"}


class EventBus:
    """Never drop terminal events. Bound logs and coalesce high-frequency progress."""
    def __init__(self):
        self.events = queue.Queue()
        self.logs = queue.Queue(maxsize=200)
        self.progress = {}
        self.guard = threading.Lock()

    def post(self, data):
        if data.get("event") == "job_progress":
            with self.guard:
                self.progress[data.get("generation")] = data
        elif data.get("kind") == "log":
            try:
                self.logs.put_nowait(data)
            except queue.Full:
                pass
        else:
            self.events.put(data)


class TurboScheduler:
    def __init__(self, videos, args, script_dir, state_path, log_path, checkpoint_dir,
                 *, worker_factory=SttClient, runner=run_captured):
        self.args = args
        self.script_dir = script_dir
        self.store = StateStore(state_path, log_path)
        self.bus = EventBus()
        self.worker_factory, self.runner = worker_factory, runner
        self.worker = None
        self.extracting = self.translating = self.recognizing = None
        self.extract_blocked = self.stt_blocked = self.translate_blocked = None
        self.stopping = False
        self.restarts = self.loads = self.initial_failures = self.recognized = 0
        self.total = len(videos)
        self.jobs = []
        self.started = time.monotonic()
        self.last_report = 0
        self.recognition_started = None
        self.last_stt_end = None
        self.metrics = dict(model_loads=[], stages=[], dispatch_gaps=[], restarts=[])
        for video in videos:
            try:
                self.jobs.append(PipelineJob(video, args, script_dir, self.store, checkpoint_dir))
            except Exception as exc:
                self.initial_failures += 1
                self.store.update(video, status="failed", stage="preflight", error=redact(exc))
                self.log("preflight", video, redact(exc))

    def log(self, stage, source, text):
        name = Path(source).name if source else "Whisper"
        core.Log.info(f"[{stage} · {name}] {redact(text)}")

    def event(self, name, **fields):
        core.gui_event(self.args, name, **fields)

    def status(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_report < 0.5:
            return
        self.last_report = now
        counts = {phase: sum(job.phase == phase for job in self.jobs) for phase in TERMINAL}
        completed = sum(counts.values()) + self.initial_failures
        failed = counts["failed"] + self.initial_failures
        pending_translation = sum(job.phase == "source_ready" for job in self.jobs)
        model = "loading" if self.worker and not self.worker.ready else "resident" if self.worker else "released"
        stages = dict(extract=str(self.extracting.inp) if self.extracting else "",
                      stt=str(self.recognizing.inp) if self.recognizing else "",
                      translate=str(self.translating.inp) if self.translating else "")
        self.event("turbo_status", total=self.total, completed=completed, failed=failed,
                   finished=counts["complete"], no_text=counts["no_text"], recognized=self.recognized,
                   pending_translation=pending_translation, stages=stages, model=model,
                   audio_ahead=sum(job.phase in {"audio_ready", "extracting"} for job in self.jobs),
                   stopping=self.stopping, extract_paused=self.extract_blocked,
                   stt_paused=self.stt_blocked, translation_paused=self.translate_blocked)

    def _has_stt_work(self):
        return any(job.phase in {"audio_ready", "extracting"} or
                   (job.phase == "pending" and not self.extract_blocked) for job in self.jobs)

    def _runner(self, job, stage):
        def run(command, **kwargs):
            return self.runner(command, **kwargs,
                log=lambda line: self.bus.post(dict(kind="log", stage=stage,
                                                    source=str(job.inp), text=line)))
        return run

    def _submit(self, pool, stage, job, action):
        started = time.monotonic()
        self.store.log(job.inp, "stage_start", stage=stage)
        future = pool.submit(action)
        def done(result):
            error = result.exception()
            self.bus.post(dict(kind="stage", stage=stage, job=job, error=error,
                               seconds=time.monotonic() - started))
        future.add_done_callback(done)

    def _extract(self, job):
        if shutil.disk_usage(job.inp.parent).free < 512 * 1024 * 1024:
            raise StageError("Less than 512 MiB free disk space; audio extraction paused", code="disk_full")
        try:
            job.extract(self._runner(job, "extract"))
        except OSError as exc:
            if exc.errno == 28 or getattr(exc, "winerror", None) == 112:
                raise StageError("Disk full; audio extraction paused", code="disk_full") from exc
            raise

    def _dispatch(self, extract_pool, translate_pool):
        if self.stopping:
            return
        if self.worker is None and not self.stt_blocked and self._has_stt_work():
            try:
                self.worker = self.worker_factory(self.script_dir, self.jobs[0].stt_config(), self.bus.post)
                self.loads += 1
                self.log("stt", None, "Loading model once for this batch")
            except OSError as exc:
                self._worker_failed(str(exc), startup=True)
        # Feed the GPU before dispatching slower housekeeping/translation work.
        if self.worker and self.worker.ready and not self.recognizing and not self.stt_blocked:
            job = next((job for job in self.jobs if job.phase == "audio_ready"), None)
            if job:
                job.begin_stt()
                self.recognizing = job
                self.recognition_started = time.monotonic()
                if self.last_stt_end is not None:
                    self.metrics["dispatch_gaps"].append(self.recognition_started - self.last_stt_end)
                try:
                    self.worker.transcribe(job)
                except (BrokenPipeError, OSError) as exc:
                    self._worker_failed(str(exc))
                else:
                    self.store.log(job.inp, "stage_start", stage="stt", attempt=job.attempt)
        if getattr(self.args, "stop_file", None) and self.args.stop_file.exists():
            self.stopping = True
            return
        ahead = sum(job.phase in {"audio_ready", "extracting"} for job in self.jobs)
        if (not self.extracting and not self.extract_blocked and not self.stt_blocked and
                ahead < int(getattr(self.args, "audio_prefetch", 2))):
            for job in self.jobs:
                if job.phase != "pending":
                    continue
                try:
                    if job.begin_extract():
                        self.extracting = job
                        self._submit(extract_pool, "extract", job, lambda item=job: self._extract(item))
                        break
                    if (sum(item.phase in {"audio_ready", "extracting"} for item in self.jobs) >=
                            int(getattr(self.args, "audio_prefetch", 2))):
                        break
                except OSError:
                    raise
                except Exception as exc:
                    job.fail(exc)
                    self.log("extract", job.inp, str(exc))
        if getattr(self.args, "stop_file", None) and self.args.stop_file.exists():
            self.stopping = True
            return
        if not self.translating and not self.translate_blocked:
            job = next((job for job in self.jobs if job.phase == "source_ready"), None)
            if job:
                try:
                    job.begin_translation()
                    self.translating = job
                    self._submit(translate_pool, "translate", job,
                                 lambda item=job: item.translate(self._runner(item, "translate")))
                except OSError:
                    raise
                except Exception as exc:
                    job.fail(exc)
                    self.log("translate", job.inp, str(exc))

    def _worker_failed(self, error, *, retry=True, startup=False):
        job = self.recognizing
        if self.worker:
            self.worker.close(graceful=False)
            self.worker = None
        self.recognizing = None
        self.log("stt", job.inp if job else None, error)
        if job:
            if retry and job.retries < 1 and self.restarts < 2:
                job.retries += 1
                job.phase = "audio_ready"
                job.save(status="audio_ready", stage="audio_ready", error=error)
            else:
                job.fail(error)
        if startup or self.restarts >= 2:
            self.stt_blocked = error
        else:
            self.restarts += 1
            self.metrics["restarts"].append(dict(error=error, job=str(job.inp) if job else None))

    def _consume(self, data):
        if data["kind"] == "stage":
            job, stage, error = data["job"], data["stage"], data["error"]
            if stage == "extract":
                self.extracting = None
            else:
                self.translating = None
            self.metrics["stages"].append(dict(job=str(job.inp), stage=stage,
                                               seconds=data["seconds"], success=error is None))
            self.store.log(job.inp, "stage_done", stage=stage, seconds=data["seconds"], success=error is None)
            if error:
                if getattr(error, "code", None) == "disk_full":
                    self.extract_blocked = str(error)
                    job.phase = "pending"
                    job.save(status="pending", stage="disk_paused", error=str(error))
                else:
                    job.fail(error)
                    if stage == "translate" and getattr(error, "code", None) in (400, 401, 403, 404, 429):
                        self.translate_blocked = str(error)
                self.log(stage, job.inp, str(error))
                return
            try:
                if stage == "extract":
                    job.commit_audio()
                else:
                    job.finalize()
            except OSError:
                raise  # Disk/state failures stop new work instead of corrupting recovery.
            except Exception as exc:
                job.fail(exc)
                self.log(stage, job.inp, str(exc))
            return
        if data["kind"] != "stt" or not self.worker or data.get("generation") != self.worker.generation:
            return
        event = data.get("event")
        if event == "worker_ready":
            self.worker.ready = True
            self.metrics["model_loads"].append(dict(seconds=data.get("load_seconds"), device=data.get("device")))
            self.log("stt", None, f"Model resident on {data.get('device')}; ready for consecutive files")
        elif event in {"worker_fatal", "worker_exit"}:
            self._worker_failed(data.get("error", "STT worker exited unexpectedly"),
                                startup=not self.worker.ready)
        elif self.recognizing and data.get("job_id") == self.recognizing.job_id and data.get("attempt") == self.recognizing.attempt:
            job = self.recognizing
            if event == "job_completed":
                self.recognizing = None
                self.last_stt_end = time.monotonic()
                self.metrics["stages"].append(dict(job=str(job.inp), stage="stt", seconds=data["seconds"], success=True))
                try:
                    job.commit_source()
                    self.recognized += 1
                    self.store.log(job.inp, "stage_done", stage="stt", seconds=data["seconds"], summary=data.get("summary"))
                except OSError:
                    raise
                except Exception as exc:
                    job.fail(exc)
            elif event == "job_failed":
                if data.get("fatal"):
                    self._worker_failed(data["error"])
                else:
                    self.recognizing = None
                    job.fail(data["error"])
                    self.log("stt", job.inp, data["error"])

    def _poll_worker(self):
        if not self.worker:
            return
        now = time.monotonic()
        if not self.worker.ready and now - self.worker.started > 1200:
            self._worker_failed("Model initialization timed out", startup=True)
        elif (self.recognizing and self.args.local_stt_timeout_minutes and
              now - self.recognition_started > self.args.local_stt_timeout_minutes * 60):
            self._worker_failed("Local STT timed out; source not committed", retry=False)
        elif not self.recognizing and (self.stopping or not self._has_stt_work() or self.stt_blocked):
            self.worker.close(graceful=self.worker.ready)
            self.worker = None

    def _drain_logs(self):
        for _ in range(30):
            try:
                data = self.bus.logs.get_nowait()
            except queue.Empty:
                break
            source = data.get("source")
            self.log(data["stage"], source, data["text"])
        with self.bus.guard:
            updates = list(self.bus.progress.values())
            self.bus.progress.clear()
        for data in updates:
            if (self.worker and self.recognizing and data.get("generation") == self.worker.generation and
                    data.get("attempt") == self.recognizing.attempt):
                self.event("turbo_stt_progress", video=str(self.recognizing.inp),
                           seconds=data.get("seconds"), duration=data.get("duration"))

    def run(self):
        self.event("batch_start", total=self.total, turbo=True)
        self.store.log(self.store.path.parent if self.store.path else Path.cwd(), "batch_start", total=self.total, turbo=True)
        extract_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio")
        translate_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translate")
        try:
            while True:
                try:
                    if getattr(self.args, "stop_file", None) and self.args.stop_file.exists():
                        self.stopping = True
                    # Apply all completed stages before considering new work.
                    for _ in range(100):
                        try:
                            self._consume(self.bus.events.get_nowait())
                        except queue.Empty:
                            break
                    self._poll_worker()
                    self._dispatch(extract_pool, translate_pool)
                    self._drain_logs()
                    self.status()
                    active = self.extracting or self.recognizing or self.translating or (self.worker and not self.worker.ready)
                    possible = ((not self.stopping) and (
                        (not self.stt_blocked and self._has_stt_work()) or
                        (not self.translate_blocked and any(job.phase == "source_ready" for job in self.jobs))))
                    if not active and not possible:
                        break
                    try:
                        self._consume(self.bus.events.get(timeout=0.05))
                    except queue.Empty:
                        pass
                except KeyboardInterrupt:
                    self.stopping = True
                    self.log("stop", None, "Finishing active stages before stopping")
        finally:
            if self.worker:
                self.worker.close(graceful=not self.recognizing)
                self.worker = None
            extract_pool.shutdown(wait=True)
            translate_pool.shutdown(wait=True)
        self.status(force=True)
        failed = self.initial_failures + sum(job.phase == "failed" for job in self.jobs)
        completed = self.initial_failures + sum(job.phase in TERMINAL for job in self.jobs)
        unfinished = self.total - completed
        code = 130 if self.stopping else 1 if failed or unfinished else 0
        self.metrics.update(total=self.total, completed=completed, failed=failed, unfinished=unfinished,
                            recognized=self.recognized, model_initializations=self.loads,
                            elapsed_seconds=time.monotonic() - self.started, stopped=self.stopping)
        if self.store.path:
            core.atomic_write_json(self.store.path.parent / ".autosub_turbo_metrics.json", self.metrics)
        self.event("batch_done", total=self.total, completed=completed, failed=failed,
                   stopped=self.stopping, unfinished=unfinished, turbo=True)
        self.store.log(self.store.path.parent if self.store.path else Path.cwd(), "batch_done", **self.metrics)
        core.Log.info(f"Turbo finished: {completed}/{self.total}; failed={failed}; pending={unfinished}; model loads={self.loads}")
        return code


def run_turbo(videos, args, script_dir, state_path, log_path, checkpoint_dir):
    return TurboScheduler(videos, args, script_dir, state_path, log_path, checkpoint_dir).run()
