"""Local operational events. Never record credentials, prompts, or call content."""

import json
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def record(stage, code, **metadata):
    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "code": code,
        **metadata,
    }
    try:
        config.RUNTIME.mkdir(parents=True, exist_ok=True)
        with _lock, (config.RUNTIME / "diagnostics.jsonl").open(
            "a", encoding="utf-8"
        ) as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # A diagnostic write must never turn a successful operation into failure.
