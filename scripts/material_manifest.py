"""Summarize local material processing without publishing transcript text or phone numbers."""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.recordings import cached_transcript, index

rows = []
for item in index().values():
    transcript = cached_transcript(item["id"])
    rows.append(
        {
            "id": item["id"],
            "title": item["title"],
            "call_time": item["call_time"],
            "transcribed": bool(transcript),
            "duration": transcript.get("duration") if transcript else None,
            "segments": len(transcript.get("segments", [])) if transcript else 0,
            "voiced_fraction": (
                transcript.get("voiced_fraction") if transcript else None
            ),
            "quality_flags": transcript.get("quality_flags", []) if transcript else [],
            "human_verified": False,
        }
    )
summary = {
    "total": len(rows),
    "transcribed": sum(r["transcribed"] for r in rows),
    "quality_flagged": sum(bool(r["quality_flags"]) for r in rows),
    "decoded_seconds": round(sum(r["duration"] or 0 for r in rows), 1),
    "human_verified": 0,
    "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    "recordings": rows,
}
(config.ROOT / "docs" / "materials.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
lines = [
    "# 真实录音处理清单",
    "",
    f"本地机器转写：{summary['transcribed']} / {summary['total']} 段；解码音频合计约 {summary['decoded_seconds']/3600:.2f} 小时。",
    f"共 {summary['quality_flagged']} 段触发机器转写质量提示，需回听确认是否漏识别或长时间静音。所有转写均未人工逐字核对、未完成可靠说话人分离，不作为企业与意向准确率金标。",
    "",
    "原始文件保留在项目外；本清单不包含手机号、原始文件名或通话全文。",
    "",
    "| 材料 | 转写片段 | 语音片段占比 | 状态 |",
    "| --- | ---: | ---: | --- |",
]
for r in rows:
    state = (
        "需重点回听"
        if r["quality_flags"]
        else "机器转写，未人工核对" if r["transcribed"] else "待转写"
    )
    fraction = (
        f"{r['voiced_fraction']*100:.1f}%" if r["voiced_fraction"] is not None else "—"
    )
    lines.append(f"| {r['title']} | {r['segments']} | {fraction} | {state} |")
(config.ROOT / "docs" / "MATERIALS.md").write_text(
    "\n".join(lines) + "\n", encoding="utf-8"
)
p = config.ROOT / "docs" / "evaluation.json"
report = json.loads(p.read_text(encoding="utf-8"))
report["materials"] = {k: v for k, v in summary.items() if k != "recordings"}
p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    json.dumps(
        {k: v for k, v in summary.items() if k != "recordings"}, ensure_ascii=False
    )
)
