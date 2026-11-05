import os

from .database import DATABASE_URL

APP_ENV = os.getenv("APP_ENV", "development")
COOKIE_SECURE = APP_ENV == "production"
ALLOWED_ORIGINS = [value.strip().rstrip("/") for value in os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if value.strip()]
SYNC_WORKER_ENABLED = os.getenv("SYNC_WORKER_ENABLED", "true").lower() == "true"
AI_REQUESTS_PER_MINUTE = int(os.getenv("AI_REQUESTS_PER_MINUTE", "10"))
MAP_REQUESTS_PER_MINUTE = int(os.getenv("MAP_REQUESTS_PER_MINUTE", "60"))
SYNC_BATCHES_PER_MINUTE = int(os.getenv("SYNC_BATCHES_PER_MINUTE", "120"))


def validate_production_settings():
    if COOKIE_SECURE and (DATABASE_URL.startswith("sqlite") or not ALLOWED_ORIGINS
                          or any(not origin.startswith("https://") for origin in ALLOWED_ORIGINS)):
        raise RuntimeError("公网模式需要 PostgreSQL 和明确的 HTTPS 网站域名，请检查 DATABASE_URL、ALLOWED_ORIGINS。")
