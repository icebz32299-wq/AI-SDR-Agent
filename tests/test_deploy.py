import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from app import config
from app.main import app
from scripts import cloud, package_deploy
from scripts.public_report import public_report


@pytest.fixture
def cloud_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path / "cloud-data")
    for key, value in {
        "LLM_API_KEY": "synthetic-provider-secret",
        "SDR_ACCESS_TOKEN": "synthetic-access-token",
        "SDR_PUBLIC_ORIGIN": "https://demo.example.test",
        "PORT": "8765",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("LLM_API_KEY", ""),
        ("SDR_ACCESS_TOKEN", "short"),
        ("SDR_PUBLIC_ORIGIN", "http://demo.example.test"),
        ("SDR_PUBLIC_ORIGIN", "https://demo.example.test/path"),
        ("SDR_PUBLIC_ORIGIN", "https://user:password@demo.example.test"),
        ("PORT", "0"),
    ],
)
def test_cloud_entry_rejects_incomplete_or_unsafe_settings(
    cloud_env, monkeypatch, key, value
):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        cloud.settings()


def test_cloud_entry_uses_platform_port_and_single_instance(cloud_env, monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    result = cloud.settings()
    assert result["port"] == 10000 and result["workers"] == 1
    assert "secret" not in json.dumps(result)


def test_https_proxy_origin_works_but_other_sites_are_rejected(cloud_env):
    auth = {"Authorization": "Bearer synthetic-access-token"}
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/leads").status_code == 401
        body = {"text": "客户：我们做家居。", "source": "synthetic", "mode": "baseline"}
        accepted = client.post(
            "/api/analyze",
            json=body,
            headers={**auth, "Origin": "https://demo.example.test"},
        )
        assert accepted.status_code == 200, accepted.text
        rejected = client.post(
            "/api/analyze",
            json=body,
            headers={**auth, "Origin": "https://unrelated.example.test"},
        )
        assert rejected.status_code == 403


def test_public_report_excludes_real_call_cases_and_material_records():
    source = {
        "real_material_checks": ["private-original"],
        "materials": ["private-filename"],
        "llm_cases": [
            {"source": "synthetic", "title": "合成测试"},
            {"source": "recording", "text": "private-transcript"},
        ],
        "test_summary": {"passed": 104},
    }
    result = public_report(source)
    text = json.dumps(result)
    assert "private" not in text and len(result["llm_cases"]) == 1
    assert result["test_summary"]["passed"] == 104


def test_deployment_archive_does_not_include_local_data_or_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(package_deploy, "ROOT", tmp_path)
    for folder in ("docs", "deploy", "app", "runtime", "scripts", "data"):
        (tmp_path / folder).mkdir()
    (tmp_path / "docs/evaluation.json").write_text(
        json.dumps({"llm_cases": [], "real_material_checks": ["private-transcript"]}),
        encoding="utf-8",
    )
    (tmp_path / "runtime/customer.json").write_text(
        "private-customer", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("LLM_API_KEY=private-key", encoding="utf-8")
    (tmp_path / "deploy/.env").write_text(
        "LLM_API_KEY=private-cloud-key", encoding="utf-8"
    )
    (tmp_path / "app/main.py").write_text("# app", encoding="utf-8")
    for name in ("app/.env.production", "app/private.mp3", "data/customer.json"):
        (tmp_path / name).write_text("private-content", encoding="utf-8")
    with ZipFile(package_deploy.package()) as archive:
        assert "AI-SDR-Agent/app/main.py" in archive.namelist()
        assert all(
            "private" not in archive.read(name).decode("utf-8")
            for name in archive.namelist()
        )
        assert not any(
            "runtime" in name or name.endswith("/.env") for name in archive.namelist()
        )
