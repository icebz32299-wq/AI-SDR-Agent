import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config, recordings, uploads
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    monkeypatch.delenv("SDR_ACCESS_TOKEN", raising=False)
    with TestClient(app) as c:
        yield c


def upload(client, name, content):
    return client.post("/api/uploads", files={"file": (name, content)})


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 1600)
    return output.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gb18030", "utf-16"])
def test_import_text_encodings_and_analyze(client, encoding):
    text = "销售：您好。\r\n客户：我们在杭州做全屋定制，设计师有5个人。"
    response = upload(client, "沟通记录.TXT", text.encode(encoding))
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["kind"] == "text" and "\r" not in item["text"]
    assert item["text"] == text.replace("\r\n", "\n")
    assert "path" not in item
    lead = client.post(
        "/api/analyze",
        json={
            "text": item["text"],
            "source": "file",
            "upload_id": item["id"],
            "mode": "baseline",
        },
    )
    assert lead.status_code == 200, lead.text
    assert len(lead.json()["result"]) == 15
    assert lead.json()["analysis"]["input_file"]["name"] == "沟通记录.TXT"
    assert "path" not in lead.json()["analysis"]["input_file"]


@pytest.mark.parametrize(
    "name,content,code",
    [
        ("empty.txt", b"", 422),
        ("blank.txt", b"  \r\n", 422),
        ("binary.txt", b"\x00\x01file", 422),
        ("file.pdf", b"%PDF-1.4", 415),
        ("fake.mp3", b"this is a text file", 422),
        ("fake.wav", b"ID3" + b"\x00" * 100, 422),
        ("fake.m4a", b"RIFF" + b"\x00" * 100, 422),
        ("long.txt", ("字" * 50001).encode(), 422),
        ("large.txt", b"x" * (uploads.TEXT_LIMIT + 1), 413),
    ],
    ids=[
        "empty",
        "blank",
        "binary",
        "unsupported",
        "bad-mp3",
        "bad-wav",
        "bad-m4a",
        "too-many-characters",
        "too-many-bytes",
    ],
)
def test_invalid_uploads_leave_no_files(client, name, content, code):
    response = upload(client, name, content)
    assert response.status_code == code, response.text
    folder = config.RUNTIME / "uploads"
    assert not folder.exists() or not list(folder.iterdir())


def test_client_filename_cannot_escape_workspace(client):
    response = upload(client, "../../outside.txt", "客户：测试文本".encode())
    assert response.status_code == 201
    item = response.json()
    assert item["name"] == "outside.txt"
    assert uploads.get_upload(item["id"])["path"] == str(
        config.RUNTIME / "uploads" / (item["id"] + ".txt")
    )
    assert not (config.RUNTIME.parent / "outside.txt").exists()


def test_uploaded_audio_playback_transcription_and_analysis(client, monkeypatch):
    content = wav_bytes()
    response = upload(client, "合成测试.wav", content)
    assert response.status_code == 201, response.text
    item = response.json()
    rid = item["id"]
    audio = client.get(f"/api/recordings/{rid}/audio")
    assert audio.status_code == 200 and audio.content == content
    assert audio.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/recordings/{rid}/transcript").json()["text"] == ""
    result = {
        "text": "客户：我们在杭州做家居。",
        "segments": [],
        "duration": 1,
        "processed_seconds": 1,
        "complete": True,
    }

    def mock_run(command, **kwargs):
        assert (
            Path(command[command.index("--input") + 1]).parent
            == config.RUNTIME / "uploads"
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps(result))

    monkeypatch.setattr(recordings.subprocess, "run", mock_run)
    monkeypatch.setattr(recordings.POOL, "submit", lambda fn, *args: fn(*args))
    started = client.post(f"/api/recordings/{rid}/transcribe").json()
    job = client.get("/api/jobs/" + started["job_id"]).json()
    assert job["status"] == "completed", job
    assert job["progress"]["percent"] == 100
    assert (
        client.get(f"/api/recordings/{rid}/transcript").json()["text"] == result["text"]
    )
    lead = client.post(
        "/api/analyze",
        json={
            "text": result["text"],
            "source": "recording",
            "recording_id": rid,
            "upload_id": rid,
            "mode": "baseline",
        },
    )
    assert lead.status_code == 200, lead.text
    assert lead.json()["recording_id"] == rid
    # Uploaded files remain separate from the assignment's material picker.
    assert all(r["id"] != rid for r in client.get("/api/recordings").json())


def test_upload_reference_validation(client):
    assert (
        client.post(
            "/api/analyze",
            json={"text": "客户：测试", "upload_id": "missing", "mode": "baseline"},
        ).status_code
        == 404
    )
    item = upload(client, "test.wav", wav_bytes()).json()
    assert (
        client.post(
            "/api/analyze",
            json={"text": "客户：测试", "upload_id": item["id"], "mode": "baseline"},
        ).status_code
        == 422
    )


def test_upload_limits_include_chunked_requests(client, monkeypatch):
    monkeypatch.setattr(uploads, "REQUEST_LIMIT", 128)
    response = client.post(
        "/api/uploads", headers={"Content-Length": "129"}, content=b"x"
    )
    assert response.status_code == 413
    response = client.post(
        "/api/uploads",
        headers={"Content-Type": "multipart/form-data; boundary=testing"},
        content=iter([b"x" * 80, b"x" * 80]),
    )
    assert response.status_code == 413, response.text
    assert (
        client.post(
            "/api/uploads", headers={"Content-Length": "invalid"}, content=b"x"
        ).status_code
        == 400
    )


def test_upload_respects_auth_and_origin(client, monkeypatch):
    monkeypatch.setenv("SDR_ACCESS_TOKEN", "test-token")
    assert upload(client, "record.txt", b"test").status_code == 401
    response = client.post(
        "/api/uploads",
        headers={
            "Authorization": "Bearer test-token",
            "Origin": "https://evil.example",
        },
        files={"file": ("record.txt", b"test")},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"text": "", "complete": True}, "未识别到可用语音"),
        ({"text": "不完整文本", "complete": False}, "未完整处理"),
    ],
)
def test_failed_asr_never_returns_partial_success(
    client, monkeypatch, result, expected
):
    rid = upload(client, "test.wav", wav_bytes()).json()["id"]
    monkeypatch.setattr(
        recordings.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(result)),
    )
    monkeypatch.setattr(recordings.POOL, "submit", lambda fn, *args: fn(*args))
    job_id = client.post(f"/api/recordings/{rid}/transcribe").json()["job_id"]
    job = client.get("/api/jobs/" + job_id).json()
    assert job["status"] == "failed" and expected in job["error"]
    assert client.get(f"/api/recordings/{rid}/transcript").json()["text"] == ""


@pytest.mark.parametrize("failure", ["timeout", "decode", "invalid_result"])
def test_asr_failures_are_actionable_and_keep_original_upload(
    client, monkeypatch, failure
):
    rid = upload(client, "test.wav", wav_bytes()).json()["id"]

    def run(*args, **kwargs):
        if failure == "timeout":
            raise recordings.subprocess.TimeoutExpired("synthetic-command", 1)
        if failure == "decode":
            return SimpleNamespace(
                returncode=1,
                stderr=json.dumps(
                    {"code": "ASR_DECODE", "message": "录音无法解码，请重新导出。"}
                ),
            )
        return SimpleNamespace(returncode=0, stdout="[]")

    monkeypatch.setattr(recordings.subprocess, "run", run)
    monkeypatch.setattr(recordings.POOL, "submit", lambda fn, *args: fn(*args))
    jid = client.post(f"/api/recordings/{rid}/transcribe").json()["job_id"]
    job = client.get("/api/jobs/" + jid).json()
    assert job["status"] == "failed" and job["error"]
    assert job["progress"]["message"] == job["error"]
    assert client.get(f"/api/recordings/{rid}/audio").status_code == 200
    assert not client.get(f"/api/recordings/{rid}/transcript").json()["text"]
    if failure == "timeout":
        assert "超时" in job["error"]
    elif failure == "decode":
        assert "解码" in job["error"]


def test_completed_job_includes_transcript_quality_for_frontend(client, monkeypatch):
    rid = upload(client, "test.wav", wav_bytes()).json()["id"]
    result = {
        "text": "客户：不需要，谢谢。",
        "segments": [{"start": 0, "end": 150}],
        "duration": 180,
        "speech_seconds": 5,
        "complete": True,
        "processed_seconds": 180,
    }
    monkeypatch.setattr(
        recordings.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(result)),
    )
    monkeypatch.setattr(recordings.POOL, "submit", lambda fn, *args: fn(*args))
    jid = client.post(f"/api/recordings/{rid}/transcribe").json()["job_id"]
    job = client.get("/api/jobs/" + jid).json()
    assert job["status"] == "completed" and job["result"]["text"] == result["text"]
    assert any("有效语音较少" in flag for flag in job["result"]["quality_flags"])
