"""Small, dependency-free progress contract shared with the ASR subprocess."""

import json
from collections import Counter
from pathlib import Path
from time import monotonic


def repetition_error(segments):
    texts = [
        str(s.get("text", "")).strip()
        for s in segments
        if str(s.get("text", "")).strip()
    ]
    if len(texts) >= 12 and Counter(texts).most_common(1)[0][1] / len(texts) > 0.6:
        return "转写出现大量重复片段，识别结果不可靠，请重新转写或回听核实。"
    return ""


def speech_coverage(segments, duration):
    duration = max(float(duration), 0.001)
    intervals = sorted(
        (
            max(0, min(duration, float(s.get("start", 0)))),
            max(0, min(duration, float(s.get("end", 0)))),
        )
        for s in segments
    )
    covered, previous_end = 0, 0
    for start, end in intervals:
        covered += max(0, end - max(start, previous_end))
        previous_end = max(previous_end, end)
    return min(covered / duration, 1)


def recovery_needed(result):
    return (
        bool(repetition_error(result.get("segments", [])))
        or (
            result.get("duration", 0) > 60
            and min(
                speech_coverage(result.get("segments", []), result["duration"]),
                result.get("speech_seconds", result["duration"]) / result["duration"],
            )
            < 0.12
        )
        or not result.get("text", "").strip()
    )


def select_transcript(results):
    def rank(result):
        segments = result.get("segments", [])
        return (
            not bool(repetition_error(segments)),
            bool(result.get("text", "").strip()),
            speech_coverage(segments, result.get("duration", 0)),
        )

    return max(results, key=rank)


def write_progress(path, **value):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.replace(target)
    except PermissionError:
        # Progress is advisory; a brief Windows reader lock must not abort ASR.
        pass


def collect_transcript(segments, info, model_name, progress_path=None, attempt=1):
    rows = []
    last_update = 0
    duration = float(info.duration)
    write_progress(
        progress_path,
        percent=1,
        duration=duration,
        processed_seconds=0,
        message=(
            "正在识别整段录音…"
            if attempt == 1
            else "首次识别不足，正在调整语音检测重试…"
        ),
    )
    # Consume the entire lazy ASR generator; never stop at a preview or word limit.
    for segment in segments:
        rows.append(
            {
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip(),
                "speaker": "unknown",
                "avg_logprob": round(segment.avg_logprob, 3),
            }
        )
        if monotonic() - last_update >= 1:
            write_progress(
                progress_path,
                percent=min(98, round(segment.end / max(duration, 0.001) * 98)),
                duration=duration,
                processed_seconds=round(segment.end, 2),
                message=(
                    "正在识别整段录音…"
                    if attempt == 1
                    else "正在重新识别，补充可能遗漏的语音…"
                ),
            )
            last_update = monotonic()
    result = {
        "text": "\n".join(f'[{row["start"]:.1f}s] {row["text"]}' for row in rows),
        "segments": rows,
        "duration": duration,
        "speech_seconds": float(getattr(info, "duration_after_vad", duration)),
        "processed_seconds": duration,
        "complete": True,
        "model": model_name,
        "asr_version": 2,
        "asr_attempts": attempt,
        "language": info.language,
        "speaker_verified": False,
        "note": "整段录音已处理；机器转写可能存在听写错误，说话人和不确定字段需核实。",
    }
    write_progress(
        progress_path,
        percent=99,
        duration=duration,
        processed_seconds=duration,
        message="整段识别完成，正在保存全文…",
    )
    return result
