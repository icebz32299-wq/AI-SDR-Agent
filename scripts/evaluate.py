"""Reproducible model checks on explicitly labelled examples, not real-call accuracy."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.agent import analyze
from app.models import SQLLead
from app.storage import init


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["llm", "baseline"], default="llm")
    args = parser.parse_args()
    init()
    samples = json.loads(
        (config.ROOT / "data" / "examples.json").read_text(encoding="utf-8")
    )
    expected = {
        "assignment": "high",
        "polite": "low",
        "correction": "low",
        "medium": "medium",
    }
    rows = []
    provider = ""
    for sample in samples:
        try:
            result, analysis = analyze(sample["text"], args.mode)
            SQLLead.model_validate(result)
            provider = analysis["provider_model"]
            row = {
                "id": sample["id"],
                "title": sample["title"],
                "source": sample["source"],
                "expected_intent": expected[sample["id"]],
                "intent_level": result["intent_level"],
                "intent_matches": result["intent_level"] == expected[sample["id"]],
                "valid_schema": len(result) == 15,
                "grounded_fields": len(analysis["evidence"]),
                "result": result,
                "analysis": analysis,
            }
            rows.append(row)
            print(
                json.dumps(
                    {
                        k: row[k]
                        for k in (
                            "id",
                            "intent_level",
                            "intent_matches",
                            "grounded_fields",
                        )
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            rows.append(
                {
                    "id": sample["id"],
                    "title": sample["title"],
                    "source": sample["source"],
                    "expected_intent": expected[sample["id"]],
                    "error": type(exc).__name__,
                }
            )
            print(sample["id"], type(exc).__name__, flush=True)
    report_path = config.ROOT / "docs" / "evaluation.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {}
    stamp = datetime.now(timezone.utc).isoformat()
    if args.mode == "llm":
        report.update(
            generated_at=stamp, mode="llm", provider_model=provider, llm_cases=rows
        )
    else:
        report.update(baseline_checked_at=stamp, baseline_cases=rows)
    report["summary"] = (
        "题目示例与合成边界案例用于验证结构、证据和意向。真实录音尚未形成独立人工金标，不宣称真实业务准确率。"
    )
    xml_path = config.ROOT / "docs" / "test-results.xml"
    if xml_path.exists():
        suites = ET.parse(xml_path).getroot().findall("testsuite")
        report["tests_passed"] = sum(
            int(s.get("tests", 0))
            - int(s.get("failures", 0))
            - int(s.get("errors", 0))
            - int(s.get("skipped", 0))
            for s in suites
        )
        report["test_summary"] = {
            "total": sum(int(s.get("tests", 0)) for s in suites),
            "passed": report["tests_passed"],
            "failed": sum(
                int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites
            ),
            "skipped": sum(int(s.get("skipped", 0)) for s in suites),
        }
    target = config.ROOT / "docs"
    target.mkdir(exist_ok=True)
    (target / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    private = config.RUNTIME / "evaluations"
    private.mkdir(parents=True, exist_ok=True)
    (private / f"{args.mode}-examples.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
