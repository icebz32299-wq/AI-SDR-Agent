"""Import user files into the local workspace; analysis always consumes text."""

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from . import config
from .storage import db, now

TEXT_LIMIT = 1 * 1024 * 1024
AUDIO_LIMIT = 50 * 1024 * 1024
REQUEST_LIMIT = AUDIO_LIMIT + 64 * 1024
EXTENSIONS = {".txt": "text", ".mp3": "audio", ".wav": "audio", ".m4a": "audio"}
MEDIA_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


def decode_text(data):
    encodings = ["utf-8-sig", "gb18030"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16"]
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise HTTPException(422, "无法读取文本编码，请另存为 UTF-8 格式的 TXT 文件")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise HTTPException(422, "文件包含二进制内容，请上传纯文本 TXT 文件")
    if len(text) < 2:
        raise HTTPException(422, "沟通记录内容不能为空，且至少需要两个字符")
    if len(text) > 50000:
        raise HTTPException(422, "沟通记录不能超过50,000字，请按通话拆分后上传")
    return text


def check_audio(data, extension):
    valid = {
        ".wav": len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE",
        ".mp3": len(data) > 16
        and (data[:3] == b"ID3" or (data[0] == 255 and data[1] & 224 == 224)),
        ".m4a": len(data) > 16 and data[4:8] == b"ftyp",
    }
    if not valid[extension]:
        raise HTTPException(
            422, "录音内容与文件格式不符，请上传有效的 MP3、WAV 或 M4A 文件"
        )


async def import_file(file: UploadFile):
    # Client filenames are display metadata only, never a filesystem path.
    name = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not name or len(name) > 240 or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "文件名无效或过长")
    extension = Path(name).suffix.lower()
    kind = EXTENSIONS.get(extension)
    if not kind:
        raise HTTPException(415, "支持 TXT 沟通记录，以及 MP3、WAV、M4A 录音")
    limit = TEXT_LIMIT if kind == "text" else AUDIO_LIMIT
    uid = "upload_" + uuid4().hex
    folder = config.RUNTIME / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / (uid + ".part")
    target = folder / (uid + extension)
    size = 0
    try:
        with partial.open("xb") as out:
            while chunk := await file.read(256 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        413,
                        (
                            "TXT 文件不能超过1 MB"
                            if kind == "text"
                            else "录音不能超过50 MB"
                        ),
                    )
                out.write(chunk)
        if not size:
            raise HTTPException(422, "文件为空，请重新选择")
        text = ""
        if kind == "text":
            text = decode_text(partial.read_bytes())
        else:
            with partial.open("rb") as source:
                check_audio(source.read(64), extension)
        partial.replace(target)
        with db() as con:
            con.execute(
                "INSERT INTO uploads(id,name,kind,extension,size,created_at) VALUES (?,?,?,?,?,?)",
                (uid, name, kind, extension, size, now()),
            )
        result = {"id": uid, "name": name, "kind": kind, "size": size}
        if kind == "text":
            result["text"] = text
        else:
            result["recording"] = {
                "id": uid,
                "title": name[:120],
                "call_time": "",
                "size": size,
                "uploaded": True,
            }
        return result
    except BaseException:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


def get_upload(uid):
    with db() as con:
        row = con.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["path"] = str(
        config.RUNTIME / "uploads" / (result["id"] + result["extension"])
    )
    return result
