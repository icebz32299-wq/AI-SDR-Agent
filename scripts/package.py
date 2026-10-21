"""Prepare shareable source, excluding local credentials, records and screenshots."""

import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.public_report import public_report

FILES = {
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-audio.txt",
    "requirements-media.txt",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "run.bat",
    "停止项目.bat",
    "data/examples.json",
    "data/brands.json",
    "data/company_references.json",
    "docs/screenshots/audit-review.jpg",
    "docs/screenshots/audit-mobile.jpg",
}
DIRECTORIES = {"app", "prompts", "scripts", "tests", "docs", "deploy"}
PRIVATE = {"docs/materials.json", "docs/MATERIALS.md", "docs/evaluation.json"}
PRIVATE_SUFFIXES = {
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
}


def shareable(path):
    name = path.as_posix()
    if name in PRIVATE or "__pycache__" in path.parts or path.suffix == ".pyc":
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.suffix.lower() in PRIVATE_SUFFIXES and name not in FILES:
        return False
    return name in FILES or path.parts[0] in DIRECTORIES


def package():
    output = ROOT / "output/AI-SDR-Agent-source.zip"
    output.parent.mkdir(exist_ok=True)
    report = json.loads((ROOT / "docs/evaluation.json").read_text(encoding="utf-8"))
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if path.is_file() and shareable(rel):
                archive.write(path, "AI-SDR-Agent/" + rel.as_posix())
        archive.writestr(
            "AI-SDR-Agent/docs/evaluation.json",
            json.dumps(public_report(report), ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "AI-SDR-Agent/docs/MATERIALS.md",
            "# 录音材料说明\n\n原始题目录音、机器转写全文、私有处理清单及真实业务页面截图不随可分享源码提供。\n\n"
            "仓库可独立运行，评审可上传自行准备的TXT或录音测试。若另有授权录音目录，可在SDR_RECORDINGS_DIR中私密配置。\n\n"
            "机器处理数量不代表识别准确率；真实业务效果仍需人工金标评估。\n",
        )
    return output


if __name__ == "__main__":
    print(package())
