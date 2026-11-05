"""数据库持久化队列；定位有时限，重启后可回收过期租约。"""
import asyncio
import json
import logging
import uuid
from datetime import timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .auth import utcnow
from .models import PairingCode, RateBucket, SyncDevice, SyncMessage, SyncSource, TutoringJob, User, UserSession
from .schemas import JobDraft
from .services.importer import preview_messages

logger = logging.getLogger(__name__)


async def process_one(bind, geocode=None) -> bool:
    now = utcnow()
    ready = or_(SyncMessage.status == "queued",
                (SyncMessage.status == "processing") & (SyncMessage.lease_until < now))
    token = str(uuid.uuid4())
    with Session(bind) as db:
        row = db.scalar(select(SyncMessage).join(SyncSource, SyncSource.id == SyncMessage.source_id)
            .join(SyncDevice, SyncDevice.id == SyncSource.device_id)
            .where(ready, or_(SyncMessage.retry_at.is_(None), SyncMessage.retry_at <= now),
                   SyncSource.enabled.is_(True), SyncDevice.revoked.is_(False))
            .order_by(SyncMessage.id).limit(1))
        if row is None:
            return False
        message_id = row.id
        claimed = db.execute(update(SyncMessage).where(SyncMessage.id == message_id, ready)
            .values(status="processing", lease_token=token, lease_until=now + timedelta(minutes=3), attempts=SyncMessage.attempts + 1)
            .execution_options(synchronize_session=False)).rowcount
        db.commit()
        if not claimed:
            return True
        row = db.get(SyncMessage, message_id)
        source = db.get(SyncSource, row.source_id)
        owner_id, source_name, city = row.owner_id, source.name, source.city
        body, approved = row.body, row.approved_drafts
        sent_at = row.sent_at.replace(tzinfo=timezone.utc) if row.sent_at else None

    try:
        drafts = []
        if not sent_at:
            state, detail = "review", "缺少可靠的原消息时间"
        elif sent_at < utcnow() - timedelta(days=3):
            state, detail = "expired", "原消息已超过三天"
        else:
            parsed = json.loads(approved) if approved else preview_messages(body, source_name)[0]
            drafts = [JobDraft.model_validate(item).model_dump() for item in parsed]
            if not drafts:
                state, detail = "ignored", "未识别到家教订单"
            elif not approved and any(not (d.get("subject") and (d.get("grade") or d.get("schedule"))
                    and d.get("salary") is not None and (d.get("location") or d.get("teaching_mode") == "线上")) for d in drafts):
                state, detail = "review", "订单字段不完整，请核对后导入"
            else:
                for draft in drafts:
                    draft["source_group"] = source_name
                    draft["city"] = draft.get("city") or city
                if geocode is None:
                    from .main import geocode_jobs
                    geocode = geocode_jobs
                await geocode(drafts, city)
                state, detail = "imported", None
        with Session(bind) as db:
            changed = db.execute(update(SyncMessage).where(SyncMessage.id == message_id, SyncMessage.lease_token == token)
                .values(status=state, detail=detail, lease_token=None, lease_until=None,
                        job_count=len(drafts) if state == "imported" else 0)).rowcount
            if not changed:
                db.rollback()
                return True
            if state == "imported":
                for index, draft in enumerate(drafts):
                    exists = db.scalar(select(TutoringJob.id).where(TutoringJob.source_message_id == message_id, TutoringJob.source_part == index))
                    if exists is None:
                        db.add(TutoringJob(**draft, owner_id=owner_id, source_message_id=message_id,
                                           source_part=index, published_at=sent_at))
            if state in ("ignored", "expired", "imported"):
                db.execute(update(SyncMessage).where(SyncMessage.id == message_id).values(body="", sender=None, approved_drafts=None))
            db.commit()
    except Exception as error:
        # 不记录消息正文、请求网址或凭证，供用户重试的原因只保留异常类别。
        with Session(bind) as db:
            row = db.get(SyncMessage, message_id)
            if row and row.lease_token == token:
                row.status = "failed" if row.attempts >= 3 else "queued"
                row.detail = f"处理失败（{type(error).__name__}），可在待确认中重新处理"
                row.retry_at = utcnow() + timedelta(seconds=30 * row.attempts)
                row.lease_token = None
                row.lease_until = None
                db.commit()
    return True


def cleanup(bind):
    now, cutoff = utcnow(), utcnow() - timedelta(days=3)
    with Session(bind) as db:
        expired = (TutoringJob.owner_id.is_not(None)) & (func.coalesce(TutoringJob.published_at, TutoringJob.created_at) < cutoff)
        counts = db.execute(select(TutoringJob.owner_id, func.count()).where(expired).group_by(TutoringJob.owner_id)).all()
        for owner_id, count in counts:
            db.execute(update(User).where(User.id == owner_id).values(expired_notice=User.expired_notice + count))
        db.execute(delete(TutoringJob).where(expired))
        for model, column in ((UserSession, UserSession.expires_at), (PairingCode, PairingCode.expires_at), (RateBucket, RateBucket.expires_at)):
            db.execute(delete(model).where(column < now))
        db.execute(update(SyncMessage).where(SyncMessage.status.in_(["review", "failed", "queued"]),
            func.coalesce(SyncMessage.sent_at, SyncMessage.received_at) < cutoff).values(status="expired", body="", sender=None, approved_drafts=None, detail="原消息已过期"))
        db.execute(delete(SyncMessage).where(SyncMessage.received_at < now - timedelta(days=7), SyncMessage.status.in_(["imported", "ignored", "expired"])))
        db.commit()


async def run_worker(bind):
    cycles = 0
    while True:
        try:
            if cycles % 30 == 0:
                cleanup(bind)
            processed = await process_one(bind)
            cycles += 1
            await asyncio.sleep(0.05 if processed else 2)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("同步队列暂时不可用：%s", type(error).__name__)
            await asyncio.sleep(5)
