import json
import pytest
from fastapi.testclient import TestClient
from app import config
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    monkeypatch.delenv("SDR_ACCESS_TOKEN", raising=False)
    with TestClient(app) as c:
        yield c


def create(client, request_id=""):
    response = client.post(
        "/api/analyze",
        json={
            "text": "客户：我们在杭州，叫测试家居。设计师5个人，出图慢。",
            "title": "合成API测试",
            "source": "synthetic",
            "mode": "baseline",
            "request_id": request_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def review_body(lead, **changes):
    return {
        "version": lead["version"],
        "reviewer": "测试员",
        "note": "对照原文核实",
        "changes": changes,
        "decision": "approve",
    }


def test_create_and_fetch_contract(client):
    lead = create(client)
    assert len(lead["result"]) == 15
    assert client.get("/api/leads/" + lead["id"]).json()["version"] == 1
    assert len(client.get("/api/leads").json()) == 1


def test_idempotence_and_conflicting_content(client):
    first = create(client, "same-request")
    second = create(client, "same-request")
    assert first["id"] == second["id"]
    r = client.post(
        "/api/analyze",
        json={
            "text": "客户：其他内容",
            "mode": "baseline",
            "request_id": "same-request",
        },
    )
    assert r.status_code == 409


def test_review_audit_and_optimistic_lock(client):
    lead = create(client)
    payload = review_body(lead, company_name="已确认名称")
    updated = client.post(f'/api/leads/{lead["id"]}/review', json=payload).json()
    assert updated["version"] == 2 and updated["status"] == "approved"
    assert updated["result"]["need_human_review"] is False
    assert len(updated["reviews"]) == 1
    assert (
        json.loads(updated["reviews"][0]["before_json"])["company_name"] != "已确认名称"
    )
    assert (
        client.post(f'/api/leads/{lead["id"]}/review', json=payload).status_code == 409
    )


def test_changing_intent_requires_new_reason(client):
    lead = create(client)
    new = "high" if lead["result"]["intent_level"] != "high" else "low"
    assert (
        client.post(
            f'/api/leads/{lead["id"]}/review', json=review_body(lead, intent_level=new)
        ).status_code
        == 422
    )


def test_alias_learning_requires_source_and_rolls_back(client):
    lead = create(client)
    payload = {**review_body(lead), "learn_alias": True}
    assert (
        client.post(f'/api/leads/{lead["id"]}/review', json=payload).status_code == 422
    )
    assert client.get(f'/api/leads/{lead["id"]}').json()["version"] == 1
    assert client.get("/api/aliases").json() == []


def test_verified_feedback_restores_name_only_in_matching_context(client):
    def lead_for(city):
        return client.post(
            "/api/analyze",
            json={
                "text": f"客户：我们在{city}做全屋定制，叫测试家居。",
                "source": "synthetic",
                "mode": "baseline",
            },
        ).json()

    original = lead_for("杭州")
    payload = {
        **review_body(original, company_name="杭州测试家居有限公司"),
        "learn_alias": True,
        "verification_source": "合成测试的主体核验来源",
    }
    response = client.post(f'/api/leads/{original["id"]}/review', json=payload)
    assert response.status_code == 200
    assert len(client.get("/api/aliases").json()) == 1
    restored = lead_for("杭州")
    assert restored["result"]["company_name"] == "杭州测试家居有限公司"
    assert restored["analysis"]["company"]["status"] == "verified"
    other_city = lead_for("苏州")
    assert other_city["analysis"]["company"]["status"] != "verified"


def test_batch_is_atomic_on_version_conflict(client):
    a, b = create(client), create(client)
    payload = {
        "items": [{"id": a["id"], "version": 1}, {"id": b["id"], "version": 999}],
        "reviewer": "测试员",
        "note": "批量核实",
        "changes": {"company_name": "批量名称"},
    }
    assert client.post("/api/reviews/batch", json=payload).status_code == 409
    assert client.get(f'/api/leads/{a["id"]}').json()["version"] == 1
    payload["items"][1]["version"] = 1
    assert client.post("/api/reviews/batch", json=payload).json()["updated"] == 2


def test_batch_saves_distinct_changes_and_audit_for_each_selected_lead(client):
    first, second, untouched = [create(client, f"individual-{i}") for i in range(3)]
    body = {
        "items": [
            {
                "id": first["id"],
                "version": 1,
                "changes": {"company_name": "企业甲", "contact_name": "张先生"},
            },
            {"id": second["id"], "version": 1, "changes": {"company_name": "企业乙"}},
        ],
        "reviewer": "审核员",
        "note": "分别对照原文核实",
        "decision": "approve",
    }
    assert client.post("/api/reviews/batch", json=body).json()["updated"] == 2
    a, b, c = [
        client.get("/api/leads/" + lead["id"]).json()
        for lead in (first, second, untouched)
    ]
    assert (
        a["result"]["company_name"] == "企业甲"
        and b["result"]["company_name"] == "企业乙"
    )
    assert (
        a["result"]["contact_name"] == "张先生"
        and b["result"]["contact_name"] == second["result"]["contact_name"]
    )
    assert all(
        x["status"] == "approved" and x["version"] == 2 and len(x["reviews"]) == 1
        for x in (a, b)
    )
    assert c["version"] == 1 and c["status"] == untouched["status"] and not c["reviews"]


def test_invalid_individual_change_rolls_back_entire_batch(client):
    first, second = [create(client, f"rollback-{i}") for i in range(2)]
    body = {
        "items": [
            {
                "id": first["id"],
                "version": 1,
                "changes": {"company_name": "不得留下的修改"},
            },
            {"id": second["id"], "version": 1, "changes": {"confidence_score": "1"}},
        ],
        "reviewer": "审核员",
        "note": "检查事务回滚",
    }
    assert client.post("/api/reviews/batch", json=body).status_code == 422
    for lead in (first, second):
        current = client.get("/api/leads/" + lead["id"]).json()
        assert (
            current["result"] == lead["result"]
            and current["version"] == 1
            and not current["reviews"]
        )


def test_explicit_uniform_change_overrides_individual_draft(client):
    lead = create(client)
    body = {
        "items": [
            {
                "id": lead["id"],
                "version": 1,
                "changes": {"industry": "原草稿行业", "contact_name": "李先生"},
            }
        ],
        "changes": {"industry": "统一核实行业"},
        "reviewer": "审核员",
        "note": "统一字段优先",
    }
    assert client.post("/api/reviews/batch", json=body).status_code == 200
    result = client.get("/api/leads/" + lead["id"]).json()["result"]
    assert result["industry"] == "统一核实行业" and result["contact_name"] == "李先生"


def test_batch_alias_feedback_is_scoped_to_explicit_item(client):
    first, second = [create(client, f"alias-item-{i}") for i in range(2)]
    body = {
        "items": [
            {
                "id": first["id"],
                "version": 1,
                "changes": {"company_name": "已核验主体甲", "industry": "家居"},
                "learn_alias": True,
                "verification_source": "客户提供的合成主体证明",
            },
            {
                "id": second["id"],
                "version": 1,
                "changes": {"company_name": "普通订正乙"},
            },
        ],
        "reviewer": "审核员",
        "note": "仅第一条反馈核验结果",
    }
    assert client.post("/api/reviews/batch", json=body).status_code == 200
    aliases = client.get("/api/aliases").json()
    assert len(aliases) == 1 and aliases[0]["company_name"] == "已核验主体甲"


def test_export_approved_only_and_csv_injection(client):
    a, b = create(client), create(client)
    client.post(
        f'/api/leads/{a["id"]}/review',
        json=review_body(a, company_name="=HYPERLINK(test)"),
    )
    assert len(client.get("/api/export").json()) == 1
    assert len(client.get("/api/export?scope=all").json()) == 2
    assert "'=HYPERLINK(test)" in client.get("/api/export?format=csv").text


def test_cross_origin_mutation_is_denied(client):
    r = client.post(
        "/api/analyze",
        json={"text": "你好", "mode": "baseline"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_optional_auth_no_secrets_in_config(client, monkeypatch):
    monkeypatch.setenv("SDR_ACCESS_TOKEN", "test-token")
    assert client.get("/api/leads").status_code == 401
    config_response = client.get(
        "/api/config", headers={"Authorization": "Bearer test-token"}
    )
    assert config_response.status_code == 200
    assert "LLM_API_KEY" not in config_response.text


def test_unknown_audio_and_whitespace_input(client):
    assert client.get("/api/recordings/not-found/audio").status_code == 404
    assert (
        client.post("/api/analyze", json={"text": "  ", "mode": "baseline"}).status_code
        == 422
    )


def test_recording_index_filters_macos_and_masks_phone(client, tmp_path, monkeypatch):
    from app import recordings

    materials = tmp_path / "synthetic-materials"
    materials.mkdir()
    name = "[1]-20261021090000-13800001234-synthetic.mp3"
    (materials / name).write_bytes(b"ID3")
    (materials / ("._" + name)).write_bytes(b"ID3")
    (materials / "__MACOSX").mkdir()
    (materials / "__MACOSX" / name).write_bytes(b"ID3")
    recordings.index.cache_clear()
    try:
        monkeypatch.setattr(config, "RECORDINGS", materials)
        data = client.get("/api/recordings").json()
        assert len(data) == 1
        assert data[0]["phone_masked"] == "138****1234"
        assert "path" not in data[0]
    finally:
        recordings.index.cache_clear()


def test_frontend_assets_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/.env").status_code == 404


@pytest.mark.parametrize(
    "items",
    [
        [{"id": [], "version": 1}],
        [{"id": "x", "version": "bad"}],
        [{"version": 1}],
        [{"id": "x", "version": 0}],
    ],
)
def test_bad_batch_items_are_validation_errors(client, items):
    response = client.post(
        "/api/reviews/batch",
        json={"items": items, "reviewer": "审核员", "note": "验证参数"},
    )
    assert response.status_code == 422


def test_idempotency_covers_metadata_and_mode(client):
    create(client, "metadata-test")
    response = client.post(
        "/api/analyze",
        json={
            "text": "客户：我们在杭州，叫测试家居。设计师5个人，出图慢。",
            "title": "不同名称",
            "source": "synthetic",
            "mode": "llm",
            "request_id": "metadata-test",
        },
    )
    assert response.status_code == 409
    assert len(client.get("/api/leads").json()) == 1


def test_concurrent_analysis_is_rejected_without_hanging(client):
    from app.main import ANALYZE_LOCK

    ANALYZE_LOCK.acquire()
    try:
        response = client.post(
            "/api/analyze", json={"text": "客户：测试", "mode": "baseline"}
        )
        assert response.status_code == 409
    finally:
        ANALYZE_LOCK.release()
    assert create(client)["id"]


def test_model_failure_does_not_hold_analysis_slot(client, monkeypatch):
    import importlib
    from app.agent import ModelError

    main = importlib.import_module("app.main")
    original = main.analyze

    def fail(*args):
        raise ModelError("合成模型异常")

    monkeypatch.setattr(main, "analyze", fail)
    response = client.post("/api/analyze", json={"text": "客户：测试模型失败"})
    assert response.status_code == 502
    assert client.get("/api/leads").json() == []
    monkeypatch.setattr(main, "analyze", original)
    assert create(client)["id"]


def test_export_does_not_silently_stop_at_one_thousand(client):
    from app.storage import db
    from uuid import uuid4

    item = create(client)
    with db() as con:
        source = list(
            con.execute("SELECT * FROM leads WHERE id=?", (item["id"],)).fetchone()
        )
        for _ in range(1001):
            copy = source.copy()
            copy[0], copy[1], copy[8] = uuid4().hex, None, "approved"
            con.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", copy)
    assert len(client.get("/api/export").json()) == 1001
    assert len(client.get("/api/export?scope=all").json()) == 1002
