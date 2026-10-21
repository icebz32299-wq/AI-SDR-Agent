"""Private deployment artifact: no local business records, recordings, or credentials."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.public_report import public_report


def package():
    public = ROOT / "deploy" / "evaluation.public.json"
    report = json.loads((ROOT / "docs" / "evaluation.json").read_text(encoding="utf-8"))
    public.write_text(
        json.dumps(public_report(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files = {
        "Dockerfile",
        ".dockerignore",
        "requirements.txt",
        "requirements-audio.txt",
        "scripts/cloud.py",
        "scripts/server.py",
        "scripts/transcribe.py",
        "deploy/compose.yaml",
        "deploy/Caddyfile",
        "deploy/.env.example",
        "deploy/evaluation.public.json",
        "docs/DEPLOYMENT.md",
        "docs/AUTODL.md",
        "data/examples.json",
        "data/company_references.json",
        "data/brands.json",
    }
    output = ROOT / "output" / "AI-SDR-Agent-deploy.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if not p.is_file() or "__pycache__" in rel.parts or p.suffix == ".pyc":
                continue
            if (
                (p.name == ".env" or p.name.startswith(".env."))
                and rel.as_posix() != "deploy/.env.example"
            ) or p.suffix.lower() in {
                ".mp3",
                ".wav",
                ".m4a",
                ".mp4",
                ".sqlite",
                ".sqlite3",
                ".db",
                ".log",
            }:
                continue
            if rel.as_posix() in files or rel.parts[0] in {"app", "prompts"}:
                archive.write(p, "AI-SDR-Agent/" + rel.as_posix())
    return output


if __name__ == "__main__":
    print(package())
