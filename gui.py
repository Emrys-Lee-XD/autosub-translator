"""Autosub desktop interface, built with Python's bundled Tkinter."""
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path

from gui_support import (ROOT, DEFAULTS, SETTINGS_PATH, ProcessRunner, build_command,
                         environment_report, load_settings, save_settings)
from language_config import LANGUAGES
from version import __version__


class AutosubApp:
    def __init__(self, root, settings_path=SETTINGS_PATH):
        self.root = root
        self.settings_path = settings_path
        self.runner = ProcessRunner()
        self.ui_events = queue.Queue()
        self.checking = False
        self.closing = False
        self.busy = False
        self.preview = False
        self.started = 0
        self.last_output_dir = None
        self.last_exit = None
        self.fields = {}
        self.controls = []
        try:
            values = load_settings(settings_path)
        except (OSError, ValueError) as exc:
            values = DEFAULTS.copy()
            root.after_idle(lambda detail=str(exc): messagebox.showerror("配置读取失败", detail, parent=root))
        self.vars = {k: (tk.BooleanVar(root, value=v) if isinstance(v, bool) else tk.StringVar(root, value=v))
                     for k, v in values.items()}
        self.status = tk.StringVar(root, value="准备就绪")
        self.detail = tk.StringVar(root, value="选择视频后，可先预演处理流程。")
        self.counter = tk.StringVar(root, value="0 / 0 个视频")
        self.elapsed = tk.StringVar(root, value="尚未开始")
        root.title(f"Autosub · 多语言字幕工作台 {__version__}")
        root.geometry(f"1080x{min(960, max(800, root.winfo_screenheight() - 100))}")
        root.minsize(1000, 800)
        root.configure(bg="#eff3f8")
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.vars["input"].trace_add("write", lambda *_: self.root.after_idle(self._mode_changed))
        self._mode_changed()
        self.root.after(100, self._poll)

    def _build(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eff3f8")
        style.configure("TLabel", background="#eff3f8", foreground="#24344b")
        style.configure("Muted.TLabel", foreground="#68788f")
        style.configure("TButton", padding=(12, 7), font=("Microsoft YaHei UI", 10))
        style.configure("Primary.TButton", background="#2864db", foreground="white", borderwidth=0)
        style.map("Primary.TButton", background=[("disabled", "#9eafcc"), ("active", "#1c51bd")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("TCheckbutton", font=("Microsoft YaHei UI", 10), background="#eff3f8")
        style.configure("TNotebook", background="#eff3f8", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(20, 8), font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  padding=[("selected", (26, 12)), ("!selected", (20, 8))],
                  font=[("selected", ("Microsoft YaHei UI", 11, "bold")),
                        ("!selected", ("Microsoft YaHei UI", 10))],
                  background=[("selected", "#ffffff"), ("!selected", "#dfe7f2")],
                  foreground=[("selected", "#172b4a"), ("!selected", "#52647e")])
        style.configure("Horizontal.TProgressbar", background="#2864db", troughcolor="#dae3ef", borderwidth=0)
        header = tk.Frame(self.root, bg="#172b4a", padx=28, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="AUTOSUB", font=("Segoe UI", 12, "bold"), fg="#9ebeff", bg="#172b4a").pack(anchor="w")
        tk.Label(header, text="多语言字幕工作台", font=("Microsoft YaHei UI", 23, "bold"), fg="white", bg="#172b4a").pack(anchor="w", pady=(2, 2))
        tk.Label(header, text="选择语言 · 本地或云端识别 · Gemini 翻译", fg="#c2cfe3", bg="#172b4a").pack(anchor="w")
        body = ttk.Frame(self.root, padding=(24, 14))
        body.pack(fill="both", expand=True)
        source = ttk.Frame(body)
        source.pack(fill="x")
        ttk.Label(source, text="01  选择素材", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(source)
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.vars["input"])
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.fields["input"] = entry
        self.controls.append(entry)
        self._button(row, "选视频/SRT", self.pick_file).pack(side="left", padx=(0, 6))
        self._button(row, "选文件夹", self.pick_folder).pack(side="left")
        ttk.Label(source, text="文件夹会包含子文件夹中的视频；已有字幕按下方策略处理。", style="Muted.TLabel").pack(anchor="w", pady=(5, 10))
        notebook = ttk.Notebook(body)
        notebook.pack(fill="x")
        self.notebook = notebook
        basic = ttk.Frame(notebook, padding=(12, 10))
        advanced = ttk.Frame(notebook, padding=(12, 10))
        notebook.add(basic, text="02  基本设置")
        notebook.add(advanced, text="高级参数")
        for pane in (basic, advanced):
            pane.columnconfigure(1, weight=1)
            pane.columnconfigure(3, weight=1)
        advanced.columnconfigure(5, weight=1)
        self._field(basic, 0, 0, "Gemini API Key", "api_key", secret=True)
        self._field(basic, 0, 2, "原语言", "source_language", {"auto": "自动检测", **LANGUAGES})
        self._field(basic, 1, 0, "目标语言", "target_language", LANGUAGES)
        self._field(basic, 1, 2, "字幕格式", "output_mode", {"bilingual": "双语", "translated": "仅译文"})
        self._field(basic, 2, 0, "语音识别", "stt_mode", {"local": "本地 Whisper", "cloud": "Google 云端"})
        self._field(basic, 2, 2, "已有字幕", "existing", {"reuse": "保留并续跑", "force": "备份后重做", "retry_no_text": "重试无文字视频"})
        ttk.Label(basic, text="API Key 会保存在本机 config.json，请勿分享此文件。", style="Muted.TLabel").grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 2))
        self._field(advanced, 0, 0, "翻译方式", "gemini_backend", {"developer": "AI Studio API Key", "vertex": "Vertex（高级）"})
        self._field(advanced, 0, 2, "翻译模型", "model")
        self._field(advanced, 0, 4, "运行设备", "device", {"auto": "自动选择", "cuda": "NVIDIA 显卡", "cpu": "CPU"})
        self._field(advanced, 1, 0, "Cloud 项目 ID", "project")
        self._field(advanced, 1, 2, "GCS 存储桶", "bucket")
        self._field(advanced, 1, 4, "云端识别语言", "cloud_language_code")
        ttk.Label(advanced, text="Cloud 凭据文件").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
        credential_row = ttk.Frame(advanced)
        credential_row.grid(row=2, column=1, columnspan=5, sticky="ew")
        credential = ttk.Entry(credential_row, textvariable=self.vars["credentials"])
        credential.pack(side="left", fill="x", expand=True)
        self.controls.append(credential)
        self.fields["credentials"] = credential
        self._button(credential_row, "浏览…", self.pick_credentials).pack(side="left", padx=(8, 0))
        ttk.Label(advanced, text="Cloud 识别需要项目、存储桶及认证；本地识别无需 Cloud 项目。", style="Muted.TLabel").grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 2))
        fields = [("Whisper 模型", "whisper_model"), ("计算精度", "compute_type"),
            ("每批翻译条数", "batch"), ("请求间隔 / 秒", "sleep"),
            ("翻译超时 / 分钟", "translate_timeout_minutes"), ("翻译重试次数", "retries"),
            ("本地超时 / 分钟¹", "local_stt_timeout_minutes"), ("云端超时 / 小时", "stt_timeout_hours"),
            ("Vertex 区域", "location"), ("重复窗口 / 秒", "dedupe_window_seconds")]
        for i, (label, key) in enumerate(fields):
            self._field(advanced, 4 + i // 3, (i % 3) * 2, label, key)
        self._field(advanced, 7, 2, "字幕过滤", "hallucination_filter", {"conservative": "保守", "off": "关闭", "aggressive": "较强"})
        self._field(advanced, 7, 4, "识别提示", "initial_prompt")
        for widget in advanced.winfo_children():
            if isinstance(widget, (ttk.Entry, ttk.Combobox)):
                widget.configure(width=14)
        keep = ttk.Checkbutton(advanced, text="完成后保留临时工作区", variable=self.vars["keep_workspace"])
        keep.grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.controls.append(keep)
        ttk.Label(advanced, text="¹ 0 表示不设超时；CPU 下 float16 自动改为 int8。", style="Muted.TLabel").grid(row=8, column=2, columnspan=4, sticky="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(12, 10))
        self.start_button = self._button(actions, "开始生成", lambda: self.start(False), "Primary.TButton")
        self.start_button.pack(side="left", padx=(0, 8))
        self.preview_button = self._button(actions, "预演", lambda: self.start(True))
        self.preview_button.pack(side="left", padx=(0, 8))
        self._button(actions, "检查环境", self.check_environment).pack(side="left", padx=(0, 8))
        self._button(actions, "加载配置", self.load).pack(side="left", padx=(0, 8))
        self._button(actions, "保存配置", self.save).pack(side="left")
        self.stop_button = ttk.Button(actions, text="完成当前视频后停止", command=self.stop, state="disabled")
        self.stop_button.pack(side="right")
        progress = ttk.Frame(body)
        progress.pack(fill="x")
        ttk.Label(progress, textvariable=self.status, font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(progress, textvariable=self.elapsed, style="Muted.TLabel").pack(side="right")
        ttk.Label(body, textvariable=self.detail, style="Muted.TLabel", wraplength=970).pack(fill="x", pady=(4, 5))
        self.bar = ttk.Progressbar(body, maximum=1, value=0)
        self.bar.pack(fill="x")
        ttk.Label(body, textvariable=self.counter, style="Muted.TLabel").pack(anchor="e", pady=(2, 6))
        log_head = ttk.Frame(body)
        log_head.pack(fill="x")
        ttk.Label(log_head, text="03  运行记录", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Button(log_head, text="打开结果目录", command=self.open_output).pack(side="right")
        ttk.Button(log_head, text="导出日志", command=self.export_log).pack(side="right", padx=6)
        self.log = ScrolledText(body, height=8, bg="#132238", fg="#d6e2f5", insertbackground="white",
                                font=("Consolas", 10), relief="flat", padx=12, pady=10, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        self._log("欢迎使用 Autosub。选择素材并确认设置后，点击“预演”可检查处理流程。")

    def _button(self, parent, text, command, style="TButton"):
        widget = ttk.Button(parent, text=text, command=command, style=style)
        self.controls.append(widget)
        return widget

    def _field(self, parent, row, col, label, key, choices=None, secret=False):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 20, 10), pady=4)
        if choices:
            choices = dict(choices)
            choices.setdefault(self.vars[key].get(), self.vars[key].get())
            display = tk.StringVar(self.root, value=choices[self.vars[key].get()])
            widget = ttk.Combobox(parent, textvariable=display, values=list(choices.values()), state="readonly", width=22)
            def sync_display(*_):
                value = self.vars[key].get()
                choices.setdefault(value, value)
                widget.configure(values=list(choices.values()))
                display.set(choices[value])
            self.vars[key].trace_add("write", sync_display)
            def changed(_event):
                self.vars[key].set(next(k for k, v in choices.items() if v == display.get()))
                self._mode_changed()
            widget.bind("<<ComboboxSelected>>", changed)
        else:
            widget = ttk.Entry(parent, textvariable=self.vars[key], width=25, show="●" if secret else "")
        widget.grid(row=row, column=col + 1, sticky="ew", pady=4)
        self.controls.append(widget)
        self.fields[key] = widget

    def _mode_changed(self):
        if self.busy:
            return
        local = self.vars["stt_mode"].get() == "local"
        srt = self.vars["input"].get().lower().endswith(".srt")
        cloud = not local and not srt
        vertex = self.vars["gemini_backend"].get() == "vertex"
        self.fields["bucket"].configure(state="normal" if cloud else "disabled")
        self.fields["project"].configure(state="normal" if cloud or vertex else "disabled")
        self.fields["credentials"].configure(state="normal" if cloud or vertex else "disabled")
        self.fields["cloud_language_code"].configure(state="normal" if cloud else "disabled")
        self.fields["location"].configure(state="normal" if vertex else "disabled")
        self.fields["api_key"].configure(state="disabled" if vertex else "normal")
        self.fields["device"].configure(state="readonly" if local and not srt else "disabled")
        self.fields["stt_mode"].configure(state="disabled" if srt else "readonly")

    def values(self):
        return {key: variable.get() for key, variable in self.vars.items()}

    def pick_file(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择视频或 SRT",
            filetypes=[("视频或字幕", "*.mp4 *.mkv *.mov *.avi *.wmv *.m4v *.webm *.ts *.srt"), ("所有文件", "*.*")])
        if path:
            self.vars["input"].set(path)
            self._mode_changed()

    def pick_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="选择视频文件夹")
        if path:
            self.vars["input"].set(path)
            self._mode_changed()

    def pick_credentials(self):
        path = filedialog.askopenfilename(parent=self.root, title="选择 Google 凭据文件", filetypes=[("JSON", "*.json")])
        if path:
            self.vars["credentials"].set(path)

    def save(self):
        try:
            save_settings(self.values(), self.settings_path)
            self._log("配置已保存到 config.json（含 API Key）。")
        except OSError as exc:
            messagebox.showerror("无法保存配置", str(exc), parent=self.root)

    def load(self):
        if self.busy:
            return
        try:
            if not Path(self.settings_path).is_file():
                raise FileNotFoundError(f"配置文件不存在：{self.settings_path}")
            values = load_settings(self.settings_path)
            for key, value in values.items():
                self.vars[key].set(value)
            self._mode_changed()
            self._log("已从 config.json 加载配置。")
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法加载配置", str(exc), parent=self.root)

    def _set_busy(self, busy):
        self.busy = busy
        for widget in self.controls:
            widget.configure(state="disabled" if busy else ("readonly" if isinstance(widget, ttk.Combobox) else "normal"))
        self.stop_button.configure(state="normal" if busy else "disabled")
        self._mode_changed()

    def start(self, preview):
        if self.busy or self.checking:
            return
        try:
            values = self.values()
            command, env = build_command(values, dry_run=preview)
        except (ValueError, OSError) as exc:
            messagebox.showerror("请检查设置", str(exc), parent=self.root)
            return
        self.preview = preview
        source = Path(command[3])
        self.last_output_dir = source if source.is_dir() else source.parent
        self.started = time.monotonic()
        self.last_exit = None
        self.bar.configure(value=0, maximum=1)
        self.counter.set("正在统计视频…")
        self.status.set("正在预演" if preview else "正在处理")
        self.detail.set("预演不会生成字幕或调用模型。" if preview else "正在准备素材…")
        self._log("\n" + "─" * 56 + ("\n开始预演" if preview else "\n开始生成字幕"))
        self._set_busy(True)
        try:
            self.runner.start(command, env)
        except Exception as exc:
            self._set_busy(False)
            self.status.set("启动失败")
            self._log(str(exc))

    def stop(self):
        if not self.busy:
            return
        try:
            self.runner.request_stop()
            self.status.set("等待当前视频完成后停止")
            self.stop_button.configure(state="disabled")
            self._log("已请求停止：当前视频会继续完成，之后不再开始新视频。")
        except OSError as exc:
            messagebox.showerror("停止请求失败", str(exc), parent=self.root)

    def close(self):
        if self.busy:
            if messagebox.askyesno("任务仍在运行", "是否在当前视频完成后停止并关闭窗口？", parent=self.root):
                self.closing = True
                self.stop()
            return
        self.root.destroy()

    def check_environment(self):
        if self.busy or self.checking:
            return
        self.checking = True
        self.status.set("正在检查本地环境")
        values = self.values()
        def worker():
            try:
                result = environment_report(values)
            except Exception as exc:
                result = f"检查失败：{exc}"
            self.ui_events.put(result)
        threading.Thread(target=worker, daemon=True).start()

    def _progress(self, data):
        event = data.get("event")
        if event == "batch_start":
            self.bar.configure(maximum=max(data["total"], 1))
            self.counter.set(f"0 / {data['total']} 个视频")
        elif event == "video_start":
            self.detail.set(f"{data['index']} / {data['total']}  ·  {Path(data['video']).name}")
        elif event in ("video_done", "batch_done"):
            self.bar.configure(value=data["completed"])
            self.counter.set(f"{data['completed']} / {data['total']} 个视频  ·  失败 {data['failed']}")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        # Keep rendering and memory bounded for long videos.
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 3000:
            self.log.delete("1.0", f"{lines - 2500}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        for _ in range(150):
            try:
                kind, data = self.runner.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                if data:
                    self._log(data)
                stage = re.search(r"Step ([1-4])/4", data)
                if stage and self.stop_button.instate(["!disabled"]):
                    names = {"1": "提取音频", "2": "语音识别", "3": "翻译字幕", "4": "保存结果"}
                    self.status.set(("预演 · " if self.preview else "正在") + names[stage.group(1)])
            elif kind == "progress":
                self._progress(data)
            elif kind == "exit":
                self.last_exit = data
                self._set_busy(False)
                if data == 0:
                    self.status.set("预演完成（未生成字幕）" if self.preview else "处理完成")
                elif data == 130:
                    self.status.set("已停止 · 保留已有结果")
                else:
                    self.status.set("处理未全部成功 · 请查看日志")
                self._log(self.status.get())
                if self.closing:
                    self.root.destroy()
                    return
        try:
            report = self.ui_events.get_nowait()
            self._log(report)
            self.checking = False
            self.status.set("环境检查完成 · 详情见日志")
        except queue.Empty:
            pass
        if self.busy:
            seconds = int(time.monotonic() - self.started)
            self.elapsed.set(f"已运行 {seconds // 60:02d}:{seconds % 60:02d}")
        self.root.after(100, self._poll)

    def open_output(self):
        folder = self.last_output_dir
        if folder is None:
            raw = self.vars["input"].get().strip().strip('"')
            if raw:
                path = Path(raw).expanduser()
                folder = path if path.is_dir() else path.parent
        if folder is None or not folder.is_dir():
            messagebox.showinfo("结果目录", "请先选择视频或文件夹。", parent=self.root)
            return
        try:
            os.startfile(str(folder.resolve()))
        except OSError as exc:
            messagebox.showerror("无法打开目录", str(exc), parent=self.root)

    def export_log(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="导出当前窗口日志", defaultextension=".txt",
                                           initialfile="autosub-log.txt", filetypes=[("文本", "*.txt")])
        if path:
            try:
                Path(path).write_text(self.log.get("1.0", "end-1c"), encoding="utf-8-sig")
            except OSError as exc:
                messagebox.showerror("日志导出失败", str(exc), parent=self.root)


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    AutosubApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
