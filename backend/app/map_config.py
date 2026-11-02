import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MAP_PROVIDER_NAME = os.getenv("MAP_PROVIDER_NAME", "").strip()
MAP_GEOCODING_API_URL = os.getenv("MAP_GEOCODING_API_URL", "").strip()
MAP_ROUTING_API_URL = os.getenv("MAP_ROUTING_API_URL", "").strip()
MAP_SERVER_API_KEY = os.getenv("MAP_SERVER_API_KEY", "").strip()
MAP_WEB_SDK_URL = os.getenv("MAP_WEB_SDK_URL", "").strip()
MAP_WEB_PUBLIC_KEY = os.getenv("MAP_WEB_PUBLIC_KEY", "").strip()


def public_map_config() -> dict:
    return {
        "provider_name": MAP_PROVIDER_NAME or None,
        "web_sdk_configured": bool(MAP_WEB_SDK_URL and MAP_WEB_PUBLIC_KEY),
        "geocoding_api_configured": bool(MAP_GEOCODING_API_URL and MAP_SERVER_API_KEY),
        "routing_api_configured": bool(MAP_ROUTING_API_URL and MAP_SERVER_API_KEY),
    }
