"""Verify exported artifacts without printing secrets or real customer content."""

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".tools"))
from app import config
import av
import imageio_ffmpeg

archive = ROOT / "output" / "AI-SDR-Agent-source.zip"
with ZipFile(archive) as z:
    names = z.namelist()
    assert not any("/.env" in n and not n.endswith(".env.example") for n in names)
    assert not any("/runtime/" in n or "/.tools/" in n or "/.venv/" in n for n in names)
    key = os.environ.get("LLM_API_KEY", "").encode()
    if key:
        assert all(key not in z.read(n) for n in names if not n.endswith("/"))
    for required in [
        "README.md",
        "app/main.py",
        "app/agent.py",
        "prompts/extract.md",
        "docs/DESIGN.md",
        "docs/ACCEPTANCE.md",
        "requirements.txt",
    ]:
        assert "AI-SDR-Agent/" + required in names
video = ROOT / "output" / "AI-SDR-Agent-demo.mp4"
with av.open(str(video)) as container:
    duration = container.duration / 1e6
    assert 300 <= duration <= 600
    assert len(container.streams.video) == 1 and len(container.streams.audio) == 1
    width, height = container.streams.video[0].width, container.streams.video[0].height
    assert width == 1280 and height == 720
subprocess.run(
    [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-i",
        str(video),
        "-f",
        "null",
        "-",
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
report = json.loads((ROOT / "docs" / "evaluation.json").read_text(encoding="utf-8"))
assert report["test_summary"]["failed"] == 0
assert all(
    c.get("valid_schema") and c.get("intent_matches") for c in report["llm_cases"]
)
assert len(report.get("real_material_checks", [])) == 2
result = {
    "source_files": len(names),
    "secret_scan": "passed",
    "private_data_excluded": True,
    "video_seconds": round(duration, 2),
    "video_dimensions": [width, height],
    "full_video_decode": "passed",
    "program_tests": report["test_summary"],
    "example_model_checks": len(report["llm_cases"]),
    "authorized_real_text_checks": len(report["real_material_checks"]),
}
(ROOT / "output" / "delivery-checks.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False))
