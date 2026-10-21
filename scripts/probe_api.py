"""Small non-sensitive API probe. Never print credentials or upstream response bodies."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config
import os
import httpx

if not os.environ.get("LLM_API_KEY"):
    raise SystemExit("LLM_API_KEY is missing")
for suffix in ("/v1/chat/completions", "/chat/completions"):
    try:
        response = httpx.post(
            config.BASE_URL + suffix,
            headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]},
            json={
                "model": config.MODEL,
                "messages": [
                    {"role": "user", "content": 'Return only this JSON: {"ok":true}'}
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 150,
                "temperature": 0,
            },
            timeout=60,
        )
        print(json.dumps({"endpoint": suffix, "status": response.status_code}))
        if response.status_code == 404:
            continue
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"].get("content") or ""
        print(
            json.dumps(
                {
                    "model": body.get("model"),
                    "valid_json": bool(json.loads(content)),
                    "usage": body.get("usage"),
                }
            )
        )
        break
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(type(exc).__name__)
        raise SystemExit(1)
