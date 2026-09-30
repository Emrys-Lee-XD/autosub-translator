#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import subprocess
import shutil
import sys
import uuid
from pathlib import Path

def check_ffmpeg():
    """启动前检查 ffmpeg 是否存在"""
    if not shutil.which("ffmpeg"):
        print("\n[Error] 'ffmpeg' not found in PATH.")
        print("Please install FFmpeg: https://ffmpeg.org/download.html")
        sys.exit(1)

def run(cmd: list[str]) -> None:
    # capture_output=True 让它平时闭嘴
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and os.environ.get("AUTOSUB_GUI") == "1" else 0
    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    
    if p.returncode != 0:
        # 只有出错时，才打印详细信息
        print(f"\n[FFmpeg Error] Return Code: {p.returncode}")
        print(f"[Command] {' '.join(cmd)}")  # 打印具体命令，方便复制调试
        print(f"[Stderr] {p.stderr}")       # 打印错误原因
        raise RuntimeError("FFmpeg conversion failed")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out_dir", default="")
    args = ap.parse_args()

    # 1. 检查环境
    check_ffmpeg()

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"[Error] File not found: {video}")
        sys.exit(1)

    out_dir = Path(args.out_dir).resolve() if args.out_dir else video.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_out = out_dir / f"{video.stem}.stt.wav"
    wav_tmp = out_dir / f".{video.stem}.stt.{uuid.uuid4().hex}.tmp.wav"

    print(f"   Extracting audio -> {wav_out.name}...", end="\r")
    
    # 2. 执行提取
    try:
        run([
            "ffmpeg", "-y", "-i", str(video),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-loglevel", "error", 
            str(wav_tmp),
        ])
        os.replace(wav_tmp, wav_out)
        print(f"   Audio extracted.              ") # 覆盖上一行的进度
    except Exception:
        wav_tmp.unlink(missing_ok=True)
        print("\n   [ERROR] Extraction failed.")
        raise

if __name__ == "__main__":
    main()
