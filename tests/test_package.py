import json
from zipfile import ZipFile

from scripts import package


def test_shareable_source_excludes_private_records_and_rewrites_report(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(package, "ROOT", tmp_path)
    files = {
        "app/main.py": "# app",
        "README.md": "# Run",
        "tests/fixtures/core_cases.json": "[]",
        "data/customer.json": "private-content",
        "runtime/lead.json": "private-content",
        "docs/materials.json": "private-content",
        "docs/MATERIALS.md": "private-content",
        "docs/screenshots/10-real-integration.png": "private-content",
        "app/.env.local": "private-content",
        "deploy/.env": "private-content",
        "app/customer.mp3": "private-content",
        ".env.example": "LLM_API_KEY=",
        "docs/evaluation.json": json.dumps(
            {"llm_cases": [], "real_material_checks": ["private-content"]}
        ),
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    with ZipFile(package.package()) as archive:
        names = archive.namelist()
        assert "AI-SDR-Agent/app/main.py" in names
        assert "AI-SDR-Agent/tests/fixtures/core_cases.json" in names
        assert "AI-SDR-Agent/.env.example" in names
        assert all(b"private-content" not in archive.read(name) for name in names)


def test_source_package_keeps_only_explicitly_reviewed_screenshots():
    from pathlib import Path

    assert package.shareable(Path("docs/screenshots/audit-review.jpg"))
    assert not package.shareable(Path("docs/screenshots/arbitrary-customer.png"))
