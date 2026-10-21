"""Assemble actual UI capture frames and local narration. No browser automation here."""

import json
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".tools"))
import imageio_ffmpeg

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
demo = ROOT / "runtime" / "demo"
out = ROOT / "output"
out.mkdir(exist_ok=True)
counts = json.loads((demo / "frame-counts.json").read_text())
chapters = json.loads((ROOT / "scripts" / "narration.json").read_text(encoding="utf-8"))
parts = []
timings = []
start = 0
for chapter in chapters:
    cid = chapter["id"]
    wavefile = demo / "audio" / f"{cid}.wav"
    with wave.open(str(wavefile)) as w:
        duration = w.getnframes() / w.getframerate()
    target = demo / f"{cid}.mp4"
    # Match the pacing of the explanation; source is an actual sampled UI recording.
    rate = counts[cid] / duration
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        str(rate),
        "-i",
        str(demo / "frames" / cid / "frame-%04d.png"),
        "-i",
        str(wavefile),
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0xf5f7f8,fps=15",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        str(duration),
        str(target),
    ]
    subprocess.run(cmd, check=True)
    parts.append(target)
    timings.append(
        {
            "id": cid,
            "title": chapter["title"],
            "start": round(start, 2),
            "duration": round(duration, 2),
            "capture_frames": counts[cid],
        }
    )
    start += duration
    print(cid, "encoded", flush=True)
concat = demo / "concat.txt"
concat.write_text(
    "".join("file '" + p.as_posix() + "'\n" for p in parts), encoding="utf-8"
)
final = out / "AI-SDR-Agent-demo.mp4"
subprocess.run(
    [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(final),
    ],
    check=True,
)
(out / "demo-chapters.json").write_text(
    json.dumps(
        {
            "duration": round(start, 2),
            "chapters": timings,
            "note": "实际界面采样录制；按讲解节奏调整画面时长，配本地合成中文语音。",
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(final, "seconds=", round(start, 2), flush=True)
