import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

RUNTIME = Path(os.environ.get("SDR_DATA_DIR") or ROOT / "runtime")
RECORDINGS = Path(
    os.environ.get("SDR_RECORDINGS_DIR") or ROOT.parent / "SDR真实通话录音"
)
MODEL = os.environ.get("LLM_MODEL", "deepseek-v4.1-flash")
PROMPT_VERSION = "1.2"
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai-proxy.org").rstrip("/")


def public_config():
    return {
        "api_version": "1.1.0",
        "upload_supported": True,
        "model": MODEL,
        "llm_configured": bool(os.environ.get("LLM_API_KEY")),
        "search_configured": bool(os.environ.get("TAVILY_API_KEY")),
        "auth_required": bool(os.environ.get("SDR_ACCESS_TOKEN")),
        "scorecard_version": "1.0",
        "prompt_version": PROMPT_VERSION,
    }
