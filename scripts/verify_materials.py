"""Integration checks on actual cached ASR text; no accuracy claims without human gold."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.agent import analyze
from app.recordings import index, cached_transcript
from app.storage import init

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=2)
parser.add_argument(
    "--allow-external",
    action="store_true",
    help="Confirm authorized transmission of real-call text to the configured proxy",
)
args = parser.parse_args()
if not args.allow_external:
    raise SystemExit(
        "未确认真实材料的外部传输授权。取得明确许可后使用--allow-external。"
    )
init()
rows = []
private = []
for item in index().values():
    transcript = cached_transcript(item["id"])
    if not transcript or len(transcript.get("segments", [])) < 10:
        continue
    result, analysis = analyze(transcript["text"], "llm", item["call_time"])
    private.append({"recording_id": item["id"], "result": result, "analysis": analysis})
    rows.append(
        {
            "recording_id": item["id"],
            "title": item["title"],
            "source": "recording",
            "duration": transcript["duration"],
            "segments": len(transcript["segments"]),
            "valid_schema": len(result) == 15,
            "grounded_fields": len(analysis["evidence"]),
            "intent_level": result["intent_level"],
            "need_human_review": result["need_human_review"],
            "speaker_verified": False,
            "gold_available": False,
        }
    )
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    if len(rows) >= args.limit:
        break
target = config.RUNTIME / "evaluations"
target.mkdir(exist_ok=True, parents=True)
(target / "real-materials.json").write_text(
    json.dumps(private, ensure_ascii=False, indent=2), encoding="utf-8"
)
p = config.ROOT / "docs" / "evaluation.json"
report = json.loads(p.read_text(encoding="utf-8"))
report["real_material_checks"] = rows
p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
