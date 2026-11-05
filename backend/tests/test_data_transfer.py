"""校验跨库复制的事务与所有权，不将 SQLite 测试冒充 PostgreSQL 实机验收。"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import ensure_schema
from app.migrate_database import copy_into_empty_database
from app.models import TutoringJob, User


def test_copy_preserves_owner_and_refuses_existing_data(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    try:
        ensure_schema(source)
        with Session(source) as db:
            db.add(User(id=7, username="测试旧账号", password_hash="测试哈希"))
            db.add(TutoringJob(id=10, owner_id=7, raw_text="已归属订单"))
            db.add(TutoringJob(id=11, owner_id=None, raw_text="等待明确归属的旧订单"))
            db.commit()
        counts = copy_into_empty_database(source, target)
        assert counts["tutoring_jobs"] == 2
        with Session(target) as db:
            assert db.get(TutoringJob, 10).owner_id == 7
            assert db.get(TutoringJob, 11).owner_id is None
            assert db.get(User, 7).username == "测试旧账号"
        with pytest.raises(ValueError, match="已有数据"):
            copy_into_empty_database(source, target)
        with Session(target) as db:
            assert len(db.scalars(select(TutoringJob)).all()) == 2
        with Session(source) as db:
            assert db.get(TutoringJob, 11).owner_id is None
    finally:
        source.dispose()
        target.dispose()
