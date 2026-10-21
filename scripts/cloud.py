"""Container entry point. Secrets must be supplied by the deployment environment."""

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config


def settings():
    if len(os.environ.get("SDR_ACCESS_TOKEN", "").strip()) < 16:
        raise ValueError("云端部署须设置至少16个字符的SDR_ACCESS_TOKEN访问码")
    if not os.environ.get("LLM_API_KEY", "").strip():
        raise ValueError("请通过云平台的机密配置设置LLM_API_KEY")
    origin = os.environ.get("SDR_PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("SDR_PUBLIC_ORIGIN必须填写最终的HTTPS站点地址，不带路径或凭据")
    port = int(os.environ.get("PORT", "8765"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT必须为有效端口")
    config.RUNTIME.mkdir(parents=True, exist_ok=True)
    return {
        "host": "0.0.0.0",
        "port": port,
        "workers": 1,
        "proxy_headers": True,
        "forwarded_allow_ips": os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    }


if __name__ == "__main__":
    import uvicorn

    try:
        options = settings()
    except ValueError as exc:
        raise SystemExit(str(exc))
    uvicorn.run("app.main:app", **options)
