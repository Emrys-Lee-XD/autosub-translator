# 公开样例

`hello.en.srt` 是人工创建的英文测试字幕，不含私人数据。预演：

```powershell
.\autosub.bat examples\hello.en.srt --source_language en --target_language zh-CN --dry_run
```

填写自己的 API Key 后去掉 `--dry_run` 即可真实翻译。结果默认写入示例所在目录，生成文件不提交。

`demo.en.wav` 是用 Windows 本地合成语音生成的英文短样例，文本为 “Hello. This is a subtitle translation test. You can choose the source and target languages.”。可用系统 FFmpeg 生成短视频：

```powershell
ffmpeg -f lavfi -i color=c=black:s=640x360:r=25 -i examples\demo.en.wav -c:v libx264 -c:a aac -shortest demo.mp4
.\autosub.bat demo.mp4 --source_language en --target_language zh-CN --device cpu --whisper_model tiny --compute_type int8
```

这会下载 tiny 模型并调用 Gemini。生成的视频、字幕和任务状态留在本机。
