import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from . import config
from .storage import db, dump, now
from .uploads import get_upload
from .asr_progress import repetition_error, speech_coverage
from .diagnostics import record

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")


@lru_cache(maxsize=1)
def index():
    items = {}
    if not config.RECORDINGS.exists():
        return items
    files = [
        p
        for p in config.RECORDINGS.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".mp3", ".wav", ".m4a")
        and "__MACOSX" not in p.parts
        and not p.name.startswith("._")
    ]
    files.sort(
        key=lambda p: (
            int(re.match(r"\[(\d+)\]", p.name)[1])
            if re.match(r"\[(\d+)\]", p.name)
            else 9999
        )
    )
    for i, path in enumerate(files):
        rid = hashlib.sha256(
            str(path.relative_to(config.RECORDINGS)).encode()
        ).hexdigest()[:16]
        stamp = re.search(r"-(20\d{12})-", path.name)
        call_time = ""
        if stamp:
            from datetime import datetime

            try:
                call_time = (
                    datetime.strptime(stamp[1], "%Y%m%d%H%M%S").isoformat() + "+08:00"
                )
            except ValueError:
                pass
        phone = re.search(r"-(1[3-9]\d{9})-", path.name)
        items[rid] = {
            "id": rid,
            "title": f"真实录音 {i+1:02d}",
            "size": path.stat().st_size,
            "call_time": call_time,
            "phone_masked": (phone[1][:3] + "****" + phone[1][-4:]) if phone else "",
            "path": str(path.resolve()),
        }
    return items


def public_recordings():
    result = []
    for value in index().values():
        item = {k: v for k, v in value.items() if k != "path"}
        item["transcribed"] = (
            config.RUNTIME / "transcripts" / f'{item["id"]}.json'
        ).exists()
        result.append(item)
    return result


def find_recording(rid):
    item = index().get(rid)
    if item:
        return item
    item = get_upload(rid)
    if item and item["kind"] == "audio" and Path(item["path"]).is_file():
        return {**item, "title": item["name"], "call_time": "", "uploaded": True}
    return None


def cached_transcript(rid):
    path = config.RUNTIME / "transcripts" / f"{rid}.json"
    if not path.exists():
        return None
    try:
        return transcript_quality(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return {
            "text": "",
            "segments": [],
            "quality_flags": ["转写缓存无法读取，请重新转写；原始录音不受影响。"],
        }


def transcript_quality(result):
    result = dict(result)
    segments = result.get("segments", [])
    duration = max(float(result.get("duration", 0)), 0.001)
    result["voiced_fraction"] = round(speech_coverage(segments, duration), 3)
    result["speech_fraction"] = round(
        min(max(float(result.get("speech_seconds", duration)), 0) / duration, 1), 3
    )
    flags = []
    if repetition_error(segments):
        flags.append(repetition_error(segments))
    if result.get("complete") is False:
        flags.append("转写未完整完成，请重新转写后再分析。")
    if (
        duration > 60
        and min(result["voiced_fraction"], result["speech_fraction"]) < 0.12
    ):
        flags.append(
            "有效语音较少，文件时长不代表通话内容长度；请回听确认静音、噪声或可能漏识别的部分。"
        )
    texts = [str(s["text"]) for s in segments if "text" in s]
    recognized_chars = len(re.sub(r"[\W_]+", "", "".join(texts)))
    covered_seconds = result["voiced_fraction"] * duration
    if texts and covered_seconds > 30 and recognized_chars < covered_seconds * 0.2:
        flags.append(
            "识别文字与片段时长不匹配，可能存在异常缓存或漏识别，请重新转写并回听核实。"
        )
    if segments and sum(s.get("avg_logprob", 0) for s in segments) / len(segments) < -1:
        flags.append("部分机器转写的模型支持较弱，请重点回听核对")
    result["quality_flags"] = flags
    return result


def run_asr(job_id, rid):
    with db() as con:
        con.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    try:
        path = find_recording(rid)["path"]
        progress_file = config.RUNTIME / "progress" / f"{job_id}.json"
        process = subprocess.run(
            [
                sys.executable,
                str(config.ROOT / "scripts" / "transcribe.py"),
                "--input",
                path,
                "--progress-file",
                str(progress_file),
            ],
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=min(max(float(os.environ.get("ASR_TIMEOUT", "3600")), 1), 14400),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if process.returncode:
            # The child emits a safe, structured error; never expose raw stderr or file paths.
            try:
                detail = json.loads(process.stderr.strip().splitlines()[-1])
                code = detail.get("code", "ASR_PROCESS")
                message = detail["message"]
                if not code.startswith("ASR_") or not isinstance(message, str):
                    raise ValueError("invalid child error")
            except (ValueError, KeyError, IndexError, AttributeError):
                code = (
                    "ASR_DECODE"
                    if any(
                        word in process.stderr
                        for word in ("InvalidDataError", "Invalid data found")
                    )
                    else "ASR_PROCESS"
                )
                message = (
                    "录音无法解码，可能已损坏或实际格式不符，请重新导出后上传。"
                    if code == "ASR_DECODE"
                    else "本地转写进程失败，请检查语音组件和本地模型。"
                )
            record(
                "asr",
                code,
                job_id=job_id,
                recording_id=rid,
                returncode=process.returncode,
            )
            raise RuntimeError(message)
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise RuntimeError("转写进程返回了无效结果，请重试；不会保存不完整文本。")
        repeated = repetition_error(result.get("segments", []))
        if repeated:
            raise RuntimeError(repeated)
        if not result.get("text", "").strip():
            raise RuntimeError("未识别到可用语音，请检查录音是否静音、损坏或声音过小。")
        if result.get("complete") is not True or result.get(
            "processed_seconds", 0
        ) < result.get("duration", 0):
            raise RuntimeError("录音未完整处理，请重新转写；不会将不完整结果用于分析。")
        target = config.RUNTIME / "transcripts"
        target.mkdir(parents=True, exist_ok=True)
        temporary = target / f"{rid}.tmp"
        temporary.write_text(dump(result), encoding="utf-8")
        temporary.replace(target / f"{rid}.json")
        record(
            "asr",
            "COMPLETED",
            job_id=job_id,
            recording_id=rid,
            segments=len(result.get("segments", [])),
            duration=result.get("duration", 0),
            attempts=result.get("asr_attempts", 1),
        )
        with db() as con:
            con.execute(
                "UPDATE jobs SET status='completed',result=? WHERE id=?",
                (dump(result), job_id),
            )
    except Exception as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            code, message = (
                "ASR_TIMEOUT",
                "本地转写超时，录音已保留，可重试或将超长录音拆分后上传。",
            )
        elif isinstance(exc, RuntimeError):
            code, message = "ASR_FAILED", str(exc)
        else:
            code, message = "ASR_PROCESS", "转写处理失败，录音已保留，请重新转写。"
        record(
            "asr",
            code,
            job_id=job_id,
            recording_id=rid,
            exception_type=type(exc).__name__,
        )
        with db() as con:
            con.execute(
                "UPDATE jobs SET status='failed',error=? WHERE id=?", (message, job_id)
            )


def start_asr(rid):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        active = con.execute(
            "SELECT id,recording_id FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()
        if active:
            return {
                "job_id": active["id"],
                "recording_id": active["recording_id"],
                "busy": True,
            }
        job_id = uuid4().hex
        con.execute(
            "INSERT INTO jobs(id,recording_id,status,created_at) VALUES (?,?,'queued',?)",
            (job_id, rid, now()),
        )
    POOL.submit(run_asr, job_id, rid)
    return {"job_id": job_id, "recording_id": rid, "busy": False}
