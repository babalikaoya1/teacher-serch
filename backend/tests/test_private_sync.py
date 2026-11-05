import asyncio
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

import app.main as main
from app.auth import utcnow
from app.bootstrap import assign_legacy_orders
from app.database import get_db
from app.models import PairingCode, SyncMessage, TutoringJob, User
from app.sync_worker import process_one, cleanup


@pytest.fixture
def users(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'private.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SYNC_WORKER_ENABLED", False)

    async def no_geocode(drafts, city=None):
        for item in drafts:
            item.update(geocode_status="failed", geocode_error="测试环境不调用地图")
        return {"attempted": len(drafts), "resolved": 0, "failed": len(drafts), "errors": []}

    monkeypatch.setattr(main, "geocode_jobs", no_geocode)

    def session():
        with Session(engine) as db:
            yield db

    main.app.dependency_overrides[get_db] = session
    with TestClient(main.app) as a, TestClient(main.app) as b:
        assert a.post("/api/auth/register", json={"username": "用户甲", "password": "测试密码甲123456"}).status_code == 201
        assert b.post("/api/auth/register", json={"username": "用户乙", "password": "测试密码乙123456"}).status_code == 201
        yield a, b, engine
    main.app.dependency_overrides.clear()
    engine.dispose()


def pair(client, name="测试电脑"):
    code = client.post("/api/wechat-sync/pairing-code").json()["code"]
    response = client.post("/api/wechat-sync/claim", json={"code": code, "name": name})
    assert response.status_code == 200
    device = response.json()
    return device, {"Authorization": f"Bearer {device['token']}"}, code


def enable_source(client, headers):
    assert client.post("/api/wechat-sync/catalog", headers=headers, json={"groups": [{"external_key": "测试群唯一标识", "name": "同名家教群"}]}).status_code == 200
    source = client.get("/api/wechat-sync/status").json()["sources"][0]
    assert client.patch(f"/api/wechat-sync/sources/{source['id']}", json={"enabled": True, "city": "北京"}).status_code == 200
    return source


def event(key="测试消息", sent_at=None):
    return {"message_key": key, "sent_at": (sent_at or utcnow()).isoformat(), "text": "初中数学家教，周末上课，薪资180元/小时，地址在海淀区"}


def test_private_orders_ai_and_mutations(users, monkeypatch):
    a, b, engine = users
    data = {"jobs": [{"raw_text": "相同内容", "subject": "数学", "source_group": "同名群"}]}
    first = a.post("/api/import/confirm", json=data).json()[0]
    second = b.post("/api/import/confirm", json=data).json()[0]
    assert first["id"] != second["id"]
    assert [j["id"] for j in a.get("/api/jobs").json()] == [first["id"]]
    assert b.patch(f"/api/jobs/{first['id']}/location", json={"location_lat": 39.9, "location_lng": 116.4}).status_code == 404
    assert b.patch(f"/api/jobs/{first['id']}/status", params={"status": "closed"}).status_code == 404

    async def check_ai(query, jobs):
        assert [job["id"] for job in jobs] == [second["id"]]
        return []

    monkeypatch.setattr(main, "find_matching_jobs", check_ai)
    assert b.post("/api/ai/search", json={"query": "找数学家教"}).status_code == 200
    b.post("/api/auth/logout")
    assert b.get("/api/jobs").status_code == 401
    assert b.post("/api/import/preview", data={"text": "数学家教"}).status_code == 401
    assert a.post("/api/import/confirm", headers={"Origin": "https://untrusted.example"}, json=data).status_code == 403


def test_device_pairing_is_one_time_scoped_and_revocable(users):
    a, b, engine = users
    device, headers, code = pair(a)
    assert a.post("/api/wechat-sync/claim", json={"code": code, "name": "重放配对"}).status_code == 400
    source = enable_source(a, headers)
    assert b.get("/api/wechat-sync/status").json()["sources"] == []
    assert b.patch(f"/api/wechat-sync/sources/{source['id']}", json={"enabled": False}).status_code == 404
    assert b.delete(f"/api/wechat-sync/devices/{device['device_id']}").status_code == 404
    _, other_headers, _ = pair(b)
    assert b.post("/api/wechat-sync/messages", headers=other_headers, json={"source_id": source["id"], "messages": [event()]}).status_code == 404
    assert a.delete(f"/api/wechat-sync/devices/{device['device_id']}").status_code == 200
    assert a.post("/api/wechat-sync/heartbeat", headers=headers, json={"status": "ready"}).status_code == 401
    assert a.post("/api/wechat-sync/messages", headers=headers, json={"source_id": source["id"], "messages": [event()]}).status_code == 401


def test_queue_replay_expiry_and_original_timestamp(users):
    a, b, engine = users
    _, headers, _ = pair(a)
    source = enable_source(a, headers)
    original_time = utcnow() - timedelta(days=2)
    payload = {"source_id": source["id"], "messages": [event(sent_at=original_time), event("过期消息", utcnow() - timedelta(days=4))]}
    assert a.post("/api/wechat-sync/messages", headers=headers, json=payload).json() == {"accepted": 2, "duplicates": 0}
    assert a.post("/api/wechat-sync/messages", headers=headers, json=payload).json() == {"accepted": 0, "duplicates": 2}
    assert asyncio.run(process_one(engine))
    jobs = a.get("/api/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["published_at"].startswith(original_time.isoformat()[:19])
    assert jobs[0]["geocode_status"] == "failed"
    assert b.get("/api/jobs").json() == []
    assert not asyncio.run(process_one(engine))
    with Session(engine) as db:
        row = db.scalar(select(SyncMessage).where(SyncMessage.message_key == "测试消息"))
        row.status = "processing"
        row.lease_token = "失联工作进程"
        row.lease_until = utcnow() - timedelta(seconds=1)
        row.approved_drafts = '[{"raw_text":"重试订单","subject":"数学"}]'
        db.commit()
    assert asyncio.run(process_one(engine))
    assert len(a.get("/api/jobs").json()) == 1
    with Session(engine) as db:
        db.execute(update(TutoringJob).values(published_at=utcnow() - timedelta(days=4)))
        db.commit()
    cleanup(engine)
    response = a.get("/api/jobs")
    assert response.json() == []
    assert response.headers["X-Expired-Jobs-Deleted"] == "1"


def test_unknown_time_requires_review_and_cannot_be_reviewed_by_other_user(users):
    a, b, engine = users
    _, headers, _ = pair(a)
    source = enable_source(a, headers)
    a.post("/api/wechat-sync/messages", headers=headers, json={"source_id": source["id"], "messages": [{**event(), "sent_at": None}]})
    pending = a.get("/api/wechat-sync/reviews").json()[0]
    assert b.get("/api/wechat-sync/reviews").json() == []
    assert b.delete(f"/api/wechat-sync/reviews/{pending['id']}").status_code == 404
    approval = {"sent_at": utcnow().isoformat(), "jobs": [{"raw_text": "人工核对订单", "subject": "数学"}]}
    assert b.post(f"/api/wechat-sync/reviews/{pending['id']}/approve", json=approval).status_code == 404
    assert a.post(f"/api/wechat-sync/reviews/{pending['id']}/approve", json=approval).status_code == 200
    asyncio.run(process_one(engine))
    assert len(a.get("/api/jobs").json()) == 1


def test_legacy_orders_need_explicit_assignment(users):
    a, b, engine = users
    with Session(engine) as db:
        db.add(TutoringJob(raw_text="历史私人订单"))
        db.commit()
    assert a.get("/api/jobs").json() == []
    assert b.get("/api/jobs").json() == []
    with Session(engine) as db:
        assert assign_legacy_orders(db, "用户甲", "测试密码甲123456") == 1
        assert assign_legacy_orders(db, "用户甲", "测试密码甲123456") == 0
    assert len(a.get("/api/jobs").json()) == 1
    assert b.get("/api/jobs").json() == []


def test_expired_pairing_code_and_heartbeat_status(users):
    a, b, engine = users
    code = a.post("/api/wechat-sync/pairing-code").json()["code"]
    with Session(engine) as db:
        db.execute(update(PairingCode).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert a.post("/api/wechat-sync/claim", json={"code": code, "name": "过期配对"}).status_code == 400
    _, headers, _ = pair(a)
    result = a.post("/api/wechat-sync/heartbeat", headers=headers, json={"status": "unsupported", "detail": "没有可读消息控件"})
    assert result.status_code == 200
    status = a.get("/api/wechat-sync/status").json()["devices"][0]
    assert status["online"] is True
    assert status["status"] == "unsupported"
    assert "token" not in str(status)


def test_two_devices_timezone_retry_and_resume(users):
    """两个账号的同名群分别入库；时区和任务恢复不改变归属、原发布时间。"""
    a, b, engine = users
    _, first_headers, _ = pair(a)
    _, second_headers, _ = pair(b)
    first = enable_source(a, first_headers)
    second = enable_source(b, second_headers)
    original = (utcnow() - timedelta(hours=2)).astimezone(timezone(timedelta(hours=8)))
    for client, headers, source in ((a, first_headers, first), (b, second_headers, second)):
        payload = {"source_id": source["id"], "messages": [event(sent_at=original)]}
        assert client.post("/api/wechat-sync/messages", headers=headers, json=payload).status_code == 202
    async def temporary_failure(drafts, city):
        raise RuntimeError("模拟可恢复的处理错误")
    assert asyncio.run(process_one(engine, geocode=temporary_failure))
    with Session(engine) as db:
        row = db.scalar(select(SyncMessage).where(SyncMessage.source_id == first["id"]))
        assert row.status == "queued" and row.attempts == 1
        assert row.sent_at.replace(tzinfo=timezone.utc) == original.astimezone(timezone.utc)
        row.retry_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert a.patch(f"/api/wechat-sync/sources/{first['id']}", json={"enabled": False}).status_code == 200
    assert asyncio.run(process_one(engine))
    assert a.get("/api/jobs").json() == []
    assert len(b.get("/api/jobs").json()) == 1
    assert a.patch(f"/api/wechat-sync/sources/{first['id']}", json={"enabled": True}).status_code == 200
    assert asyncio.run(process_one(engine))
    first_jobs, second_jobs = a.get("/api/jobs").json(), b.get("/api/jobs").json()
    assert len(first_jobs) == len(second_jobs) == 1
    assert first_jobs[0]["id"] != second_jobs[0]["id"]
    assert first_jobs[0]["published_at"].startswith(original.astimezone(timezone.utc).isoformat()[:19])
    assert not asyncio.run(process_one(engine))
