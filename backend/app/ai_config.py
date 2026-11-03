import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

LLM_CHAT_COMPLETIONS_URL = os.getenv("LLM_CHAT_COMPLETIONS_URL", "").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))


def public_ai_config() -> dict:
    return {
        "configured": bool(LLM_CHAT_COMPLETIONS_URL and LLM_API_KEY and LLM_MODEL),
        "model": LLM_MODEL or None,
    }
