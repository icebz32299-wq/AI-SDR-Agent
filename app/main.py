import csv
import hashlib
import hmac
import io
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, recordings, uploads
from .agent import ModelError, analyze, search_company
from .models import AnalyzeRequest, BatchReview, ReviewRequest, SQLLead
from .storage import db, dump, init, now, unpack
from .diagnostics import record

ANALYZE_LOCK = threading.Lock()
EDITABLE = set(SQLLead.model_fields) - {"confidence_score", "need_human_review"}


@contextmanager
def analysis_slot():
    if not ANALYZE_LOCK.acquire(blocking=False):
        raise HTTPException(409, "已有通话正在分析，请完成后再提交")
    try:
        yield
    finally:
        ANALYZE_LOCK.release()


@asynccontextmanager
async def lifespan(app):
    init()
    with db() as con:
        con.execute(
            "UPDATE jobs SET status='failed',error='服务重启，请重新发起转写' WHERE status IN ('queued','running')"
        )
    yield


app = FastAPI(title="AI SDR Agent", version="1.1.0", lifespan=lifespan)


class UploadBodyLimit:
    """Bound multipart bytes before the parser writes its temporary files."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/api/uploads":
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > uploads.REQUEST_LIMIT:
                raise HTTPException(413, "上传请求过大，单段录音不能超过50 MB")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(UploadBodyLimit)


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        token = os.environ.get("SDR_ACCESS_TOKEN", "")
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token and not hmac.compare_digest(token, supplied):
            return JSONResponse({"detail": "请输入访问令牌"}, status_code=401)
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            allowed_origins = {str(request.base_url).rstrip("/")}
            public_origin = os.environ.get("SDR_PUBLIC_ORIGIN", "").rstrip("/")
            if public_origin:
                allowed_origins.add(public_origin)
            if origin and origin.rstrip("/") not in allowed_origins:
                return JSONResponse({"detail": "拒绝跨来源写入"}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "请求长度无效"}, status_code=400)
            limit = (
                uploads.REQUEST_LIMIT
                if request.url.path == "/api/uploads"
                else 2_000_000
            )
            if length < 0:
                return JSONResponse({"detail": "请求长度无效"}, status_code=400)
            if length > limit:
                return JSONResponse({"detail": "请求过大"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


@app.exception_handler(ModelError)
async def model_error(request, exc):
    record("model", exc.code)
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=502)


@app.get("/api/config")
def public_config():
    return config.public_config()


@app.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/api/samples")
def samples():
    return json.loads(
        (config.ROOT / "data" / "examples.json").read_text(encoding="utf-8")
    )


@app.post("/api/uploads", status_code=201)
async def upload(file: UploadFile):
    try:
        return await uploads.import_file(file)
    finally:
        await file.close()


@app.get("/api/leads")
def list_leads():
    with db() as con:
        rows = con.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT 1000"
        ).fetchall()
    return [unpack(row) for row in rows]


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not row:
            raise HTTPException(404, "线索不存在")
        result = unpack(row)
        result["reviews"] = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM reviews WHERE lead_id=? ORDER BY id DESC", (lead_id,)
            )
        ]
    return result


@app.post("/api/analyze")
def create_lead(body: AnalyzeRequest):
    if not body.text.strip():
        raise HTTPException(422, "通话内容不能为空")
    if body.recording_id and not recordings.find_recording(body.recording_id):
        raise HTTPException(404, "录音不存在")
    input_file = uploads.get_upload(body.upload_id) if body.upload_id else None
    if body.upload_id and not input_file:
        raise HTTPException(404, "上传文件不存在，请重新导入")
    if (
        input_file
        and input_file["kind"] == "audio"
        and body.recording_id != body.upload_id
    ):
        raise HTTPException(422, "上传录音与当前通话记录不匹配")
    # A bounded local queue also makes request_id retries idempotent before spending API tokens.
    request_hash = hashlib.sha256(
        dump(body.model_dump(exclude={"request_id"})).encode()
    ).hexdigest()
    with analysis_slot():
        if body.request_id:
            with db() as con:
                row = con.execute(
                    "SELECT * FROM leads WHERE request_id=?", (body.request_id,)
                ).fetchone()
            if row:
                existing = unpack(row)
                old_hash = existing["analysis"].get("request_hash")
                if (old_hash and old_hash != request_hash) or (
                    not old_hash and existing["text"] != body.text
                ):
                    raise HTTPException(409, "相同请求编号对应不同内容，请重新提交")
                return existing
        result, analysis = analyze(body.text, body.mode, body.call_time)
        analysis["request_hash"] = request_hash
        if input_file:
            analysis["input_file"] = {
                k: input_file[k] for k in ("id", "name", "kind", "size")
            }
        if body.recording_id:
            transcript = recordings.cached_transcript(body.recording_id)
            if transcript and transcript.get("quality_flags"):
                analysis["review_reasons"].extend(transcript["quality_flags"])
                result["need_human_review"] = True
        lid = uuid4().hex
        stamp = now()
        with db() as con:
            con.execute(
                "INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                (
                    lid,
                    body.request_id or None,
                    body.title,
                    body.text,
                    body.source,
                    body.recording_id,
                    dump(result),
                    dump(analysis),
                    "pending" if result["need_human_review"] else "ready",
                    stamp,
                    stamp,
                ),
            )
        return get_lead(lid)


def apply_review(con, lid, body):
    row = con.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
    if not row:
        raise HTTPException(404, "线索不存在")
    if row["version"] != body.version:
        raise HTTPException(409, "线索已更新，请刷新后重新审核")
    if not body.reviewer.strip() or len(body.note.strip()) < 2:
        raise HTTPException(422, "请填写审核人和具体审核说明")
    if not set(body.changes) <= EDITABLE:
        raise HTTPException(422, "存在不可直接修改的字段")
    before = json.loads(row["result"])
    after = {**before, **body.changes}
    if any(len(v) > 3000 for v in body.changes.values()):
        raise HTTPException(422, "修改内容过长")
    if (
        body.changes.get("intent_level", before["intent_level"])
        != before["intent_level"]
        and not body.changes.get("intent_reason", "").strip()
    ):
        raise HTTPException(422, "调整意向等级时必须填写新的判断依据")
    after["need_human_review"] = body.decision != "approve"
    try:
        after = SQLLead.model_validate(after).model_dump()
    except ValueError:
        raise HTTPException(422, "修改内容不符合SQL字段要求")
    status = "approved" if body.decision == "approve" else "rejected"
    stamp = now()
    con.execute(
        "UPDATE leads SET result=?,status=?,version=version+1,updated_at=? WHERE id=?",
        (dump(after), status, stamp, lid),
    )
    con.execute(
        "INSERT INTO reviews(lead_id,reviewer,note,decision,before_json,after_json,from_version,verification_source,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            lid,
            body.reviewer,
            body.note,
            body.decision,
            dump(before),
            dump(after),
            row["version"],
            body.verification_source,
            stamp,
        ),
    )
    if body.learn_alias:
        analysis = json.loads(row["analysis"])
        raw = analysis["company"]["raw_name"]
        if (
            body.decision != "approve"
            or not raw
            or not after["company_name"]
            or not after["area"]
            or not after["industry"]
            or not body.verification_source.strip()
        ):
            raise HTTPException(
                422, "学习企业别名需要审核通过，并填写企业名称、地区、行业和核验来源"
            )
        con.execute(
            "INSERT OR REPLACE INTO aliases(alias,company_name,area,industry,source,reviewer,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                raw,
                after["company_name"],
                after["area"],
                after["industry"],
                body.verification_source,
                body.reviewer,
                stamp,
            ),
        )


@app.post("/api/leads/{lid}/review")
def review(lid: str, body: ReviewRequest):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        apply_review(con, lid, body)
    return get_lead(lid)


@app.post("/api/reviews/batch")
def batch_review(body: BatchReview):
    ids = [i.id for i in body.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "批量线索编号无效或重复")
    try:
        requests = [
            (
                item.id,
                ReviewRequest(
                    version=item.version,
                    reviewer=body.reviewer,
                    note=body.note,
                    changes={**item.changes, **body.changes},
                    decision=body.decision,
                    learn_alias=item.learn_alias,
                    verification_source=item.verification_source,
                ),
            )
            for item in body.items
        ]
    except (KeyError, ValueError):
        raise HTTPException(422, "批量请求缺少有效版本号")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        for lid, review_body in requests:
            apply_review(con, lid, review_body)
    return {"updated": len(requests)}


@app.get("/api/aliases")
def aliases():
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM aliases ORDER BY id DESC")]


@app.get("/api/export")
def export(format: str = "json", scope: str = "approved"):
    if format not in ("json", "csv") or scope not in ("approved", "all"):
        raise HTTPException(422, "导出选项无效")
    with db() as con:
        where = " WHERE status='approved'" if scope == "approved" else ""
        rows = con.execute(
            "SELECT result FROM leads" + where + " ORDER BY created_at DESC"
        ).fetchall()
    data = [json.loads(row["result"]) for row in rows]
    if format == "json":
        return Response(
            dump(data),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="sql-leads.json"'},
        )
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(SQLLead.model_fields))
    writer.writeheader()
    for row in data:
        # Prevent spreadsheet formula execution after CSV import.
        writer.writerow(
            {
                k: (
                    "'" + v
                    if isinstance(v, str)
                    and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                )
                for k, v in row.items()
            }
        )
    return Response(
        "\ufeff" + out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sql-leads.csv"'},
    )


@app.get("/api/recordings")
def list_recordings():
    return recordings.public_recordings()


@app.get("/api/recordings/{rid}/audio")
def audio(rid: str):
    item = recordings.find_recording(rid)
    if not item:
        raise HTTPException(404, "录音不存在")
    from pathlib import Path

    return FileResponse(
        item["path"], media_type=uploads.MEDIA_TYPES[Path(item["path"]).suffix.lower()]
    )


@app.get("/api/recordings/{rid}/transcript")
def transcript(rid: str):
    if not recordings.find_recording(rid):
        raise HTTPException(404, "录音不存在")
    return recordings.cached_transcript(rid) or {
        "text": "",
        "segments": [],
        "note": "尚未转写",
    }


@app.post("/api/recordings/{rid}/transcribe")
def transcribe(rid: str):
    if not recordings.find_recording(rid):
        raise HTTPException(404, "录音不存在")
    return recordings.start_asr(rid)


@app.get("/api/jobs/{jid}")
def job(jid: str):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise HTTPException(404, "转写任务不存在")
    item = dict(row)
    item["result"] = json.loads(item["result"]) if item["result"] else None
    progress_path = config.RUNTIME / "progress" / f'{item["id"]}.json'
    try:
        item["progress"] = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        item["progress"] = {"percent": 0, "message": "正在等待本地转写…"}
    if item["status"] == "completed":
        if item["result"]:
            item["result"] = recordings.transcript_quality(item["result"])
        item["progress"].update(percent=100, message="整段转写已完成")
    elif item["status"] == "failed":
        item["progress"]["message"] = item["error"] or "转写未完成，请重试"
    return item


@app.post("/api/leads/{lid}/search")
def search(lid: str):
    lead = get_lead(lid)
    result = lead["result"]
    return {
        "results": search_company(
            result["company_name"], result["area"], result["industry"]
        ),
        "note": "网页仅用于企业候选查找，不能自动视为工商核验结论；不发送手机号或通话全文。",
    }


@app.get("/api/evaluation")
def evaluation():
    path = config.ROOT / "docs" / "evaluation.json"
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"status": "not_run"}
    )


app.mount(
    "/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static"
)


@app.get("/")
def home():
    return FileResponse(config.ROOT / "app" / "static" / "index.html")
