import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

root = Path(__file__).resolve().parent.parent
report_path = root / "docs" / "evaluation.json"
report = json.loads(report_path.read_text(encoding="utf-8"))
suites = ET.parse(root / "docs" / "test-results.xml").getroot().findall("testsuite")
report["tests_passed"] = sum(
    int(s.get("tests", 0))
    - int(s.get("failures", 0))
    - int(s.get("errors", 0))
    - int(s.get("skipped", 0))
    for s in suites
)
report["test_summary"] = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total": sum(int(s.get("tests", 0)) for s in suites),
    "passed": report["tests_passed"],
    "failed": sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites),
    "skipped": sum(int(s.get("skipped", 0)) for s in suites),
}
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Test report synchronized:", report["tests_passed"])
