"""GUI configuration and process runner; no Tk or cloud imports."""
import importlib.util
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from model_config import DEFAULT_MODEL, DEFAULT_LOCATION, LEGACY_DEFAULT_MODELS
from language_config import LANGUAGES, language_tag

ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "config.json"
DEFAULTS = dict(input="", project="", model=DEFAULT_MODEL, api_key="",
    gemini_backend="developer", source_language="auto", target_language="zh-CN",
    output_mode="bilingual", cloud_language_code="",
    stt_mode="local", device="auto", whisper_model="large-v3", compute_type="default",
    location=DEFAULT_LOCATION, bucket="", credentials="", batch="20", sleep="1", retries="3",
    translate_timeout_minutes="10", stt_timeout_hours="3", local_stt_timeout_minutes="0",
    hallucination_filter="off", dedupe_window_seconds="0.1", initial_prompt="",
    existing="reuse", keep_workspace=False)
CHOICES = dict(stt_mode=("local", "cloud"), device=("auto", "cuda", "cpu"),
    hallucination_filter=("off", "conservative", "aggressive"), existing=("reuse", "force", "retry_no_text"),
    gemini_backend=("developer", "vertex"), source_language=("auto", *LANGUAGES),
    target_language=tuple(LANGUAGES), output_mode=("bilingual", "translated"))
NUMBERS = {"batch": (int, 1, "每批翻译条数"), "sleep": (float, 0, "请求间隔"),
    "retries": (int, 1, "重试次数"), "translate_timeout_minutes": (int, 1, "翻译超时"),
    "stt_timeout_hours": (float, 0.000001, "云端识别超时"),
    "local_stt_timeout_minutes": (int, 0, "本地识别超时"),
    "dedupe_window_seconds": (float, 0, "重复字幕时间窗口")}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
EVENT_PREFIX = "__AUTOSUB_EVENT__"


def python_executable():
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return str(executable)


def load_settings(path=SETTINGS_PATH):
    values = DEFAULTS.copy()
    path = Path(path)
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        saved = {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} 的 JSON 格式错误：第 {exc.lineno} 行。") from exc
    if not isinstance(saved, dict):
        raise ValueError(f"{path.name} 的顶层必须是 JSON 对象。")
    for key, default in DEFAULTS.items():
        item = saved.get(key, default)
        if key in ("source_language", "target_language"):
            values[key] = language_tag(item, allow_auto=key == "source_language")
            continue
        if key in NUMBERS and type(item) in (int, float):
            item = str(item)
        if isinstance(item, type(default)) and (key not in CHOICES or item in CHOICES[key]):
            values[key] = item
    if values["model"] in LEGACY_DEFAULT_MODELS:
        values["model"] = DEFAULT_MODEL
    return values


def save_settings(values, path=SETTINGS_PATH):
    path = Path(path)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps({k: values[k] for k in DEFAULTS}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def build_command(values, dry_run=False):
    values = {**DEFAULTS, **values}
    raw = values["input"].strip().strip('"')
    if not raw:
        raise ValueError("请先选择视频文件或文件夹。")
    source = Path(raw).expanduser().resolve()
    if not source.exists():
        raise ValueError("选择的路径不存在。")
    is_srt = source.is_file() and source.suffix.lower() == ".srt"
    if source.is_file() and source.suffix.lower() not in {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v", ".webm", ".ts", ".srt"}:
        raise ValueError("请选择支持的视频、SRT 文件或视频文件夹。")
    required = [("model", "翻译模型")]
    if values["gemini_backend"] == "vertex" or (values["stt_mode"] == "cloud" and not is_srt):
        required.append(("project", "Google Cloud 项目 ID"))
    if values["gemini_backend"] == "vertex":
        required.append(("location", "区域"))
    if values["stt_mode"] == "local" and not is_srt:
        required.extend((("whisper_model", "Whisper 模型"), ("compute_type", "计算精度")))
    for name, label in required:
        if not values[name].strip():
            raise ValueError(f"请填写{label}。")
    for name, choices in CHOICES.items():
        if name in ("source_language", "target_language"):
            values[name] = language_tag(values[name], allow_auto=name == "source_language")
            continue
        if values[name] not in choices:
            raise ValueError(f"无效选项：{name}")
    if values["stt_mode"] == "cloud" and not is_srt and not values["bucket"].strip():
        raise ValueError("云端识别需要填写 GCS 存储桶。")
    if values["stt_mode"] == "cloud" and not is_srt and values["source_language"] == "auto" and not values["cloud_language_code"].strip():
        raise ValueError("云端识别选自动语言时，请填写语音识别语言代码。")
    active_numbers = {"batch", "sleep", "retries", "translate_timeout_minutes"}
    if not is_srt:
        active_numbers |= ({"local_stt_timeout_minutes", "dedupe_window_seconds"}
                           if values["stt_mode"] == "local" else {"stt_timeout_hours"})
    for name in active_numbers:
        convert, minimum, label = NUMBERS[name]
        try:
            parsed = convert(values[name])
        except (TypeError, ValueError):
            raise ValueError(f"{label}需要有效数值。") from None
        if not math.isfinite(parsed) or parsed < minimum:
            raise ValueError(f"{label}必须为有限数值，且不小于 {minimum:g}。")
    credential = values["credentials"].strip().strip('"')
    if credential and (values["stt_mode"] == "cloud" and not is_srt or values["gemini_backend"] == "vertex") and not Path(credential).expanduser().is_file():
        raise ValueError("所选凭据文件不存在。留空可使用系统已有凭据。")
    cmd = [python_executable(), "-u", str(ROOT / "main.py"), str(source), "--no_config"]
    fields = ["model", "gemini_backend", "source_language", "target_language", "output_mode",
              "stt_mode", *sorted(active_numbers)]
    if not is_srt and values["stt_mode"] == "local":
        fields += ["device", "whisper_model", "compute_type", "hallucination_filter"]
    if values["gemini_backend"] == "vertex" or values["stt_mode"] == "cloud" and not is_srt:
        fields.append("project")
    if values["gemini_backend"] == "vertex":
        fields.append("location")
    for name in fields:
        value = str(values[name]).strip()
        if name == "compute_type" and values["device"] == "cpu" and value == "float16":
            value = "int8"
        # Equals keeps values beginning with '-' from becoming extra CLI flags.
        cmd.append(f"--{name}={value}")
    for name in ("bucket", "initial_prompt", "cloud_language_code"):
        relevant = ((name == "bucket" or name == "cloud_language_code") and values["stt_mode"] == "cloud" and not is_srt
                    or name == "initial_prompt" and values["stt_mode"] == "local" and not is_srt)
        if relevant and values[name].strip():
            cmd.append(f"--{name}={values[name].strip()}")
    if values["existing"] != "reuse":
        cmd.append("--" + values["existing"])
    if values["keep_workspace"]:
        cmd.append("--keep_workspace")
    if dry_run:
        cmd.append("--dry_run")
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", AUTOSUB_GUI="1")
    if values["gemini_backend"] == "developer":
        env.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
        env.pop("GOOGLE_CLOUD_PROJECT", None)
        if values["api_key"].strip():
            env["GEMINI_API_KEY"] = values["api_key"].strip()
            env.pop("GOOGLE_API_KEY", None)
        elif env.get("GEMINI_API_KEY"):
            env.pop("GOOGLE_API_KEY", None)
    if credential and (values["stt_mode"] == "cloud" and not is_srt or values["gemini_backend"] == "vertex"):
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(Path(credential).expanduser().resolve())
    return cmd, env


def environment_report(values):
    lines = [f"Python：{python_executable()}"]
    for name in ("ffmpeg", "ffprobe"):
        lines.append(f"{name}：" + (shutil.which(name) or "未找到"))
    modules = ["google.genai"]
    is_srt = str(values["input"]).lower().endswith(".srt")
    if not is_srt:
        modules += ["faster_whisper"] if values["stt_mode"] == "local" else ["google.cloud.speech_v1", "google.cloud.storage"]
    for module in modules:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        lines.append(f"{module}：{'已安装' if found else '未安装'}")
    lines.append("检查仅确认本地组件；不会下载模型或调用云端服务。")
    lines.append("CUDA、项目权限及云端模型可用性需在实际处理时验证。")
    return "\n".join(lines)


class ProcessRunner:
    """Workers never call Tk. Stop requests finish the current video first."""
    def __init__(self):
        self.events = queue.Queue(maxsize=2000)
        self._guard = threading.Lock()
        self._thread = None
        self._stop_file = None
        self.running = False
        self.last_returncode = None

    def start(self, command, env):
        with self._guard:
            if self.running:
                raise RuntimeError("已有任务正在运行。")
            self.running = True
            self.last_returncode = None
            self._stop_file = Path(tempfile.gettempdir()) / f"autosub-stop-{uuid.uuid4().hex}"
            args = list(command) + ["--gui_events", "--stop_file", str(self._stop_file)]
            self._thread = threading.Thread(target=self._work, args=(args, env), daemon=True)
            self._thread.start()

    def request_stop(self):
        with self._guard:
            if self.running:
                self._stop_file.touch(exist_ok=True)

    def _work(self, command, env):
        code = 1
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                  errors="replace", bufsize=1, creationflags=flags) as process:
                for line in process.stdout:
                    line = ANSI.sub("", line).rstrip("\r\n")
                    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                        secret = env.get(key_name)
                        if secret:
                            line = line.replace(secret, "[REDACTED]")
                    if line.startswith(EVENT_PREFIX):
                        try:
                            event = json.loads(line[len(EVENT_PREFIX):])
                            if not isinstance(event, dict):
                                raise ValueError("invalid event")
                            self.events.put(("progress", event))
                            continue
                        except ValueError:
                            pass
                    self.events.put(("log", line))
                code = process.wait()
        except Exception as exc:
            self.events.put(("log", f"启动或读取任务失败：{exc}"))
        finally:
            with self._guard:
                try:
                    self._stop_file.unlink(missing_ok=True)
                except OSError:
                    pass
                self.running = False
                self.last_returncode = code
            self.events.put(("exit", code))
