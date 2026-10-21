"""Predeclared synthetic challenge checks; never a real-call accuracy benchmark."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config
from app.agent import analyze
from app.models import SQLLead
from app.storage import init


def check_case(case, result, analysis):
    failures = []
    SQLLead.model_validate(result)
    for key, expected in case.get("expected", {}).items():
        if result[key] != expected:
            failures.append(f"{key}: expected {expected!r}, got {result[key]!r}")
    for key, words in case.get("forbidden", {}).items():
        if any(word in result[key] for word in words):
            failures.append(f"{key}: contains forbidden value")
    for key, words in case.get("contains_any", {}).items():
        if not any(word in result[key] for word in words):
            failures.append(f"{key}: missing expected quantity")
    if (
        "company_status" in case
        and analysis["company"]["status"] != case["company_status"]
    ):
        failures.append("company status differs")
    strengths = {row["key"]: row["strength"] for row in analysis["intent"]["card"]}
    for key, expected in case.get("signal_strengths", {}).items():
        if strengths[key] != expected:
            failures.append(
                f"{key} strength: expected {expected}, got {strengths[key]}"
            )
    if (
        "refusal" in case
        and bool(analysis["intent"]["refusal"]["value"]) != case["refusal"]
    ):
        failures.append("current refusal differs")
    reason = case.get("review_reason_contains")
    if reason and not any(reason in item for item in analysis["review_reasons"]):
        failures.append("review routing reason missing")
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/core-evaluation.json"
    )
    args = parser.parse_args()
    cases = json.loads(
        (ROOT / "tests/fixtures/core_cases.json").read_text(encoding="utf-8")
    )
    init()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "developer-authored synthetic challenges; not independent real-call accuracy",
        "prompt_version": config.PROMPT_VERSION,
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        row = {"id": case["id"], "title": case["title"], "source": "synthetic"}
        try:
            result, analysis = analyze(case["text"], "llm")
            row.update(
                passed=not (failures := check_case(case, result, analysis)),
                failures=failures,
                input_hash=hashlib.sha256(case["text"].encode()).hexdigest(),
                result=result,
                analysis=analysis,
            )
        except Exception as exc:
            row.update(passed=False, failures=[type(exc).__name__])
        report["cases"].append(row)
        report["summary"] = {
            "total": len(report["cases"]),
            "passed": sum(item["passed"] for item in report["cases"]),
        }
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {"id": row["id"], "passed": row["passed"], "failures": row["failures"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
    return int(report["summary"]["passed"] != len(cases))


if __name__ == "__main__":
    raise SystemExit(main())
