"""Transcribe a selected number or all original recordings; resumable cache per recording."""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
from app.recordings import index

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=0)
parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
args = parser.parse_args()
folder = config.RUNTIME / "transcripts"
folder.mkdir(parents=True, exist_ok=True)
items = list(index().values())
if args.limit:
    items = items[: args.limit]


def transcribe_one(pair):
    i, item = pair
    path = folder / f'{item["id"]}.json'
    if path.exists():
        return
    print(f'{i+1}/{len(items)} {item["title"]} starting', flush=True)
    response = subprocess.run(
        [
            sys.executable,
            str(config.ROOT / "scripts" / "transcribe.py"),
            "--input",
            item["path"],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if response.returncode:
        print("Failed:", response.stderr[-2000:], flush=True)
        raise SystemExit(1)
    result = json.loads(response.stdout)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
    print(f'{item["title"]} completed: {len(result["segments"])} segments', flush=True)


with ThreadPoolExecutor(max_workers=args.workers) as pool:
    list(pool.map(transcribe_one, enumerate(items)))
