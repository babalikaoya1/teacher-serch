import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MAP_WEB_SDK_URL = os.getenv("MAP_WEB_SDK_URL", "").strip()
MAP_WEB_PUBLIC_KEY = os.getenv("MAP_WEB_PUBLIC_KEY", "").strip()


def public_map_config() -> dict:
    return {
        "sdk_url": MAP_WEB_SDK_URL or None,
        "public_key": MAP_WEB_PUBLIC_KEY or None,
        "web_sdk_configured": bool(MAP_WEB_SDK_URL and MAP_WEB_PUBLIC_KEY),
        "geocoding_api_configured": bool(MAP_WEB_SDK_URL and MAP_WEB_PUBLIC_KEY),
        "routing_api_configured": False,
        "provider_name": "高德地图" if "amap.com" in MAP_WEB_SDK_URL.lower() else None,
    }
