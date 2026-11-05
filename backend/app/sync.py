import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user, digest, rate_limit, utcnow
from .database import get_db
from .models import PairingCode, SyncDevice, SyncSource, SyncMessage, User
from .schemas import JobDraft
from .settings import SYNC_BATCHES_PER_MINUTE

router = APIRouter(prefix="/api/wechat-sync", tags=["微信同步"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("sent_at", "earliest_at", check_fields=False)
    @classmethod
    def normalize_time(cls, value):
        # SQLite 不保留时区，入库前统一为 UTC，避免三天有效期偏移。
        return value.astimezone(timezone.utc) if value else None


class Claim(StrictModel):
    code: str = Field(min_length=8, max_length=32)
    name: str = Field(min_length=1, max_length=80)


class Heartbeat(StrictModel):
    status: Literal["ready", "unsupported", "wechat_offline", "locked", "error"]
    detail: str | None = Field(default=None, max_length=240)


class Group(StrictModel):
    external_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=120)


class Catalog(StrictModel):
    groups: list[Group] = Field(max_length=200)


class SourceUpdate(StrictModel):
    enabled: bool
    city: str | None = Field(default=None, max_length=80)


class Event(StrictModel):
    message_key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=10000)
    sender: str | None = Field(default=None, max_length=120)
    sent_at: AwareDatetime | None = None


class Batch(StrictModel):
    source_id: str
    messages: list[Event] = Field(max_length=100)


class Progress(StrictModel):
    source_id: str
    status: Literal["reading", "live", "partial", "paused", "error"]
    detail: str | None = Field(default=None, max_length=240)
    earliest_at: AwareDatetime | None = None


class Review(StrictModel):
    sent_at: AwareDatetime
    jobs: list[JobDraft] = Field(min_length=1, max_length=100)


def current_device(request: Request, db: Session = Depends(get_db)) -> SyncDevice:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "缺少设备凭证，请重新配对")
    device = db.scalar(select(SyncDevice).where(SyncDevice.token_hash == digest(authorization[7:]), SyncDevice.revoked.is_(False)))
    if device is None:
        raise HTTPException(401, "设备已解除绑定或凭证无效")
    rate_limit(db, f"device:{device.id}", SYNC_BATCHES_PER_MINUTE)
    return device


def source_for_device(db: Session, source_id: str, device: SyncDevice):
    source = db.scalar(select(SyncSource).where(SyncSource.id == source_id,
        SyncSource.device_id == device.id, SyncSource.owner_id == device.owner_id))
    if source is None:
        raise HTTPException(404, "未找到已绑定群来源")
    return source


@router.post("/pairing-code")
def issue_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(db, f"pair:{user.id}", 5)
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
    expires = utcnow() + timedelta(minutes=5)
    db.add(PairingCode(code_hash=digest(code), owner_id=user.id, expires_at=expires))
    db.commit()
    return {"code": code, "expires_at": expires}


@router.post("/claim")
def claim(payload: Claim, request: Request, db: Session = Depends(get_db)):
    rate_limit(db, f"claim:{request.client.host if request.client else 'unknown'}", 10)
    owner_id = db.execute(update(PairingCode).where(PairingCode.code_hash == digest(payload.code.strip().upper()),
        PairingCode.consumed.is_(False), PairingCode.expires_at > utcnow()).values(consumed=True).returning(PairingCode.owner_id)).scalar_one_or_none()
    if owner_id is None:
        db.rollback()
        raise HTTPException(400, "配对码无效、已使用或已过期")
    token = secrets.token_urlsafe(32)
    device = SyncDevice(id=str(uuid.uuid4()), owner_id=owner_id, name=payload.name, token_hash=digest(token))
    db.add(device)
    db.commit()
    return {"device_id": device.id, "token": token}


@router.post("/heartbeat")
def heartbeat(payload: Heartbeat, device: SyncDevice = Depends(current_device), db: Session = Depends(get_db)):
    device.status, device.detail, device.last_seen_at = payload.status, payload.detail, utcnow()
    db.commit()
    sources = db.scalars(select(SyncSource).where(SyncSource.device_id == device.id, SyncSource.enabled.is_(True))).all()
    return {"sources": [{"id": item.id, "external_key": item.external_key, "name": item.name,
        "since": utcnow() - timedelta(days=3), "revision": item.revision} for item in sources], "poll_seconds": 10}


@router.post("/catalog")
def catalog(payload: Catalog, device: SyncDevice = Depends(current_device), db: Session = Depends(get_db)):
    for item in payload.groups:
        existing = db.scalar(select(SyncSource).where(SyncSource.device_id == device.id, SyncSource.external_key == item.external_key))
        if existing is None:
            db.add(SyncSource(id=str(uuid.uuid4()), owner_id=device.owner_id, device_id=device.id,
                external_key=item.external_key, name=item.name))
        else:
            existing.name = item.name
    db.commit()
    return {"message": "已更新可选择的群来源"}


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    devices = db.scalars(select(SyncDevice).where(SyncDevice.owner_id == user.id, SyncDevice.revoked.is_(False))).all()
    sources = db.scalars(select(SyncSource).join(SyncDevice, SyncDevice.id == SyncSource.device_id)
        .where(SyncSource.owner_id == user.id, SyncDevice.revoked.is_(False))).all()
    counts = db.execute(select(SyncMessage.source_id, SyncMessage.status, func.count(), func.sum(SyncMessage.job_count))
        .where(SyncMessage.owner_id == user.id).group_by(SyncMessage.source_id, SyncMessage.status)).all()
    grouped = {}
    for source_id, state, count, job_count in counts:
        grouped.setdefault(source_id, {})[state] = count
        grouped[source_id]["orders"] = grouped[source_id].get("orders", 0) + (job_count or 0)
    return {
        "devices": [{"id": d.id, "name": d.name, "status": d.status, "detail": d.detail,
            "last_seen_at": d.last_seen_at, "online": bool(d.last_seen_at and
            d.last_seen_at.replace(tzinfo=timezone.utc) > utcnow() - timedelta(seconds=45))} for d in devices],
        "sources": [{"id": s.id, "device_id": s.device_id, "name": s.name, "enabled": s.enabled,
            "city": s.city, "status": s.status, "detail": s.detail, "earliest_at": s.earliest_at,
            "last_success_at": s.last_success_at, "counts": grouped.get(s.id, {})} for s in sources],
    }


@router.delete("/devices/{device_id}")
def revoke(device_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    device = db.scalar(select(SyncDevice).where(SyncDevice.id == device_id, SyncDevice.owner_id == user.id))
    if device is None:
        raise HTTPException(404, "未找到这台设备")
    device.revoked = True
    db.execute(update(SyncSource).where(SyncSource.device_id == device.id).values(enabled=False, status="paused", detail="设备已解除绑定"))
    db.commit()
    return {"message": "已解除绑定，原设备凭证已失效"}


@router.patch("/sources/{source_id}")
def configure(source_id: str, payload: SourceUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = db.scalar(select(SyncSource).join(SyncDevice, SyncDevice.id == SyncSource.device_id).where(
        SyncSource.id == source_id, SyncSource.owner_id == user.id, SyncDevice.revoked.is_(False)))
    if source is None:
        raise HTTPException(404, "未找到该群来源")
    source.enabled, source.city = payload.enabled, payload.city
    source.revision += 1
    source.status = "waiting" if payload.enabled else "paused"
    source.detail = "等待电脑助手读取" if payload.enabled else "用户已暂停"
    db.commit()
    return {"message": "已更新同步设置"}


@router.post("/messages", status_code=202)
def ingest(payload: Batch, device: SyncDevice = Depends(current_device), db: Session = Depends(get_db)):
    source = source_for_device(db, payload.source_id, device)
    if not source.enabled:
        raise HTTPException(409, "该群同步已暂停")
    inserted, duplicates = 0, 0
    for event in payload.messages:
        if event.sent_at and event.sent_at > utcnow() + timedelta(minutes=5):
            raise HTTPException(422, "消息时间晚于当前时间，请检查电脑时钟")
    for event in payload.messages:
        old = bool(event.sent_at and event.sent_at < utcnow() - timedelta(days=3))
        state = "expired" if old else ("queued" if event.sent_at else "review")
        try:
            with db.begin_nested():
                db.add(SyncMessage(owner_id=device.owner_id, source_id=source.id, message_key=event.message_key,
                    body="" if old else event.text, sender=event.sender, sent_at=event.sent_at, status=state,
                    detail="原消息已超过三天" if old else ("消息时间不明确，请确认" if not event.sent_at else None)))
                db.flush()
            inserted += 1
        except IntegrityError:
            duplicates += 1
    db.commit()
    return {"accepted": inserted, "duplicates": duplicates}


@router.post("/progress")
def progress(payload: Progress, device: SyncDevice = Depends(current_device), db: Session = Depends(get_db)):
    source = source_for_device(db, payload.source_id, device)
    source.status = payload.status if source.enabled else "paused"
    source.detail = payload.detail
    if payload.earliest_at:
        source.earliest_at = payload.earliest_at
    if payload.status in ("live", "partial"):
        source.last_success_at = utcnow()
    db.commit()
    return {"message": "已更新读取进度"}


@router.get("/reviews")
def reviews(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(SyncMessage, SyncSource.name).join(SyncSource, SyncSource.id == SyncMessage.source_id)
        .where(SyncMessage.owner_id == user.id, SyncMessage.status.in_(["review", "failed"]))
        .order_by(SyncMessage.id.desc()).limit(100)).all()
    return [{"id": m.id, "source_group": name, "text": m.body, "sent_at": m.sent_at,
        "detail": m.detail, "status": m.status} for m, name in rows]


@router.post("/reviews/{message_id}/approve")
def approve(message_id: int, payload: Review, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not utcnow() - timedelta(days=3) <= payload.sent_at <= utcnow() + timedelta(minutes=5):
        raise HTTPException(422, "只能导入最近三天内的消息，请填写实际发布时间")
    message = db.scalar(select(SyncMessage).where(SyncMessage.id == message_id, SyncMessage.owner_id == user.id,
        SyncMessage.status.in_(["review", "failed"])))
    if not message:
        raise HTTPException(404, "未找到待确认消息")
    changed = db.execute(update(SyncMessage).where(SyncMessage.id == message.id, SyncMessage.status.in_(["review", "failed"]))
        .values(sent_at=payload.sent_at, approved_drafts=json.dumps([j.model_dump(mode="json") for j in payload.jobs], ensure_ascii=False),
                status="queued", detail=None, attempts=0, retry_at=None)).rowcount
    db.commit()
    return {"queued": bool(changed)}


@router.delete("/reviews/{message_id}")
def dismiss(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    changed = db.execute(update(SyncMessage).where(SyncMessage.id == message_id, SyncMessage.owner_id == user.id,
        SyncMessage.status.in_(["review", "failed"])).values(status="ignored", body="", detail="用户已忽略")).rowcount
    db.commit()
    if not changed:
        raise HTTPException(404, "未找到待确认消息")
    return {"message": "已忽略"}


@router.get("/download")
def download(user: User = Depends(current_user)):
    import os
    path = Path(os.getenv("WECHAT_HELPER_PACKAGE") or str(Path(__file__).resolve().parents[2] / "desktop_helper" / "dist" / "微信同步助手.exe"))
    if not path.is_file():
        raise HTTPException(503, "助手安装包尚未发布，请按部署文档打包并设置 WECHAT_HELPER_PACKAGE")
    return FileResponse(path, filename="微信同步助手.exe", media_type="application/octet-stream")
