"""Build the cloud demonstration report using only assignment/synthetic checks."""

import json
from pathlib import Path


def public_report(report):
    allowed = (
        "generated_at",
        "mode",
        "provider_model",
        "summary",
        "tests_passed",
        "test_summary",
    )
    result = {key: report[key] for key in allowed if key in report}
    result["llm_cases"] = [
        case
        for case in report.get("llm_cases", [])
        if case.get("source") in ("assignment_example", "synthetic")
    ]
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    report = json.loads((root / "docs" / "evaluation.json").read_text(encoding="utf-8"))
    target = root / "deploy" / "evaluation.public.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        json.dumps(public_report(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Public demonstration report prepared; private material checks excluded.")
