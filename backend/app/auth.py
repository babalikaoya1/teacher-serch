import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import RateBucket, User, UserSession
from .settings import ALLOWED_ORIGINS, COOKIE_SECURE

router = APIRouter(prefix="/api/auth", tags=["账号"])
COOKIE_NAME = "teacher_session"


def utcnow():
    return datetime.now(timezone.utc)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${value.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, value = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return kind == "scrypt" and hmac.compare_digest(actual.hex(), value)
    except (ValueError, TypeError):
        return False


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin.rstrip("/") not in ALLOWED_ORIGINS:
        raise HTTPException(403, "请求来源不在允许的网站范围内")


def rate_limit(db: Session, key: str, limit: int, seconds: int = 60):
    """数据库固定时间窗限额，多个服务进程共享计数。"""
    window = int(time.time()) // seconds
    bucket_key = f"{digest(key)}:{window}"
    try:
        with db.begin_nested():
            db.add(RateBucket(key=bucket_key, hits=0, expires_at=utcnow() + timedelta(seconds=seconds * 2)))
            db.flush()
    except IntegrityError:
        pass
    changed = db.execute(update(RateBucket).where(RateBucket.key == bucket_key, RateBucket.hits < limit)
                         .values(hits=RateBucket.hits + 1)).rowcount
    db.commit()
    if not changed:
        raise HTTPException(429, "请求过于频繁，请稍后重试", headers={"Retry-After": str(seconds)})


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    check_origin(request)
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(UserSession, digest(token)) if token else None
    if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= utcnow():
        raise HTTPException(401, "请先登录，或重新登录已过期的账号")
    user = db.get(User, session.owner_id)
    if user is None:
        raise HTTPException(401, "账号已失效")
    return user


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[\w\u4e00-\u9fff-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.casefold()


def begin_session(db: Session, user: User, response: Response):
    token = secrets.token_urlsafe(32)
    db.add(UserSession(token_hash=digest(token), owner_id=user.id, expires_at=utcnow() + timedelta(days=7)))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=7 * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="lax", path="/api")
    response.headers["Cache-Control"] = "no-store"
    return {"id": user.id, "username": user.username}


@router.post("/register", status_code=201)
def register(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    rate_limit(db, f"register:{request.client.host if request.client else 'unknown'}", 5, 3600)
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该账号名已被使用")
    return begin_session(db, user, response)


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    rate_limit(db, f"login-ip:{request.client.host if request.client else 'unknown'}", 20)
    rate_limit(db, f"login-user:{payload.username}", 10)
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user:
        hash_password(payload.password)
        raise HTTPException(401, "账号或密码不正确")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "账号或密码不正确")
    return begin_session(db, user, response)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    db.execute(delete(UserSession).where(UserSession.token_hash == digest(request.cookies.get(COOKIE_NAME, ""))))
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/api", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return {"message": "已退出登录"}
