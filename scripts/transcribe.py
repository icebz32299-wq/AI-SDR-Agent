"""Optional local ASR. No call audio is sent to an external service."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / ".tools").exists():
    sys.path.insert(0, str(ROOT / ".tools"))
sys.path.insert(0, str(ROOT))
from app import config
from app.asr_progress import (
    collect_transcript,
    recovery_needed,
    select_transcript,
    write_progress,
)


class ASRFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--model", default=os.environ.get("ASR_MODEL", "small"))
    parser.add_argument("--progress-file")
    args = parser.parse_args()
    write_progress(args.progress_file, percent=0, message="正在加载本地语音模型…")
    from faster_whisper import WhisperModel

    cache = config.RUNTIME / "models"
    snapshots = (
        list(
            (
                cache / f"models--Systran--faster-whisper-{args.model}" / "snapshots"
            ).glob("*")
        )
        if not Path(args.model).is_dir()
        else []
    )
    local = (
        Path(args.model)
        if Path(args.model).is_dir()
        else next((p for p in snapshots if (p / "model.bin").exists()), None)
    )
    try:
        model = WhisperModel(
            str(local) if local else args.model,
            device=os.environ.get("ASR_DEVICE", "cpu"),
            compute_type="int8",
            download_root=str(cache),
            cpu_threads=max(1, min(16, int(os.environ.get("ASR_CPU_THREADS", "4")))),
            local_files_only=not args.prepare,
        )
    except (ImportError, MemoryError):
        raise
    except Exception as exc:
        raise ASRFailure(
            "ASR_MODEL_LOAD",
            "本地语音模型加载失败，请检查模型文件和 ASR_DEVICE 设置；未准备模型时运行 python scripts/transcribe.py --prepare。",
        ) from exc
    if args.prepare:
        print(json.dumps({"prepared": args.model}))
        return
    if not args.input:
        parser.error("--input is required unless --prepare is used")
    audio, audio_info = load_audio(args.input)
    result = transcribe_with_recovery(model, audio, args.model, args.progress_file)
    result["audio_info"] = audio_info
    print(json.dumps(result, ensure_ascii=False))


def load_audio(path):
    """Avoid phase cancellation in stereo phone recordings, then boost quiet files."""
    import av
    import numpy as np
    from faster_whisper.audio import decode_audio

    with av.open(path) as container:
        if not container.streams.audio:
            raise ValueError("NO_AUDIO_STREAM")
        channels = container.streams.audio[0].codec_context.channels
    phase_recovered = False
    if channels == 2:
        left, right = decode_audio(path, split_stereo=True)
        audio = (left + right) / 2
        channel_power = [float(np.mean(left * left)), float(np.mean(right * right))]
        if float(np.mean(audio * audio)) < max(channel_power) * 0.04:
            audio = left if channel_power[0] >= channel_power[1] else right
            phase_recovered = True
    else:
        audio = decode_audio(path)
    if not audio.size:
        raise ValueError("EMPTY_AUDIO")
    peak = float(np.max(np.abs(audio)))
    gain = min(8.0, 0.3 / peak) if 0 < peak < 0.1 else 1.0
    audio = np.ascontiguousarray(audio * gain, dtype=np.float32)
    return audio, {
        "channels": channels,
        "phase_recovered": phase_recovered,
        "gain": round(gain, 3),
    }


def transcribe_with_recovery(model, audio, model_name, progress_path=None):
    candidates = []
    for attempt in (1, 2):
        options = dict(
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        if attempt == 1:
            options["initial_prompt"] = (
                "中文销售电话，酷家乐，家居，全屋定制，设计师，门店。"
            )
        else:
            # A lower speech threshold rescues quiet/brief speech without decoding long silence.
            options["vad_parameters"] = {
                "threshold": 0.3,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
            }
        segments, info = model.transcribe(audio, **options)
        result = collect_transcript(segments, info, model_name, progress_path, attempt)
        candidates.append(result)
        if not recovery_needed(result):
            break
    selected = select_transcript(candidates)
    selected["asr_attempts"] = len(candidates)
    selected["selected_attempt"] = candidates.index(selected) + 1
    return selected


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        name = type(exc).__name__
        if isinstance(exc, ASRFailure):
            code, message = exc.code, str(exc)
        elif isinstance(exc, (ImportError, ModuleNotFoundError)):
            code, message = (
                "ASR_DEPENDENCY",
                "本地语音组件未就绪，请安装 requirements-audio.txt 后重试。",
            )
        elif name in ("InvalidDataError", "EOFError", "FileNotFoundError") or str(
            exc
        ) in ("NO_AUDIO_STREAM", "EMPTY_AUDIO"):
            code, message = (
                "ASR_DECODE",
                "录音无法解码或没有音轨，请重新导出为 MP3、WAV 或 M4A。",
            )
        elif isinstance(exc, (OSError, RuntimeError)) and any(
            word in str(exc).lower()
            for word in (
                "model.bin",
                "tokenizer",
                "local cache",
                "snapshot",
                "cached",
                "local_files_only",
            )
        ):
            code, message = (
                "ASR_MODEL_MISSING",
                "本地语音模型文件缺失，请运行 python scripts/transcribe.py --prepare 后重试。",
            )
        elif isinstance(exc, MemoryError) or "out of memory" in str(exc).lower():
            code, message = (
                "ASR_MEMORY",
                "本地语音识别内存不足，请关闭占用内存的程序后重试。",
            )
        else:
            code, message = (
                "ASR_PROCESS",
                "本地语音识别处理失败，请查看本地诊断记录或重新导出录音后重试。",
            )
        print(
            json.dumps(
                {"code": code, "message": message, "exception_type": name},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        sys.exit(1)
