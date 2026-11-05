"""显式初始化历史订单归属，不能把旧数据交给第一个注册者。"""
import getpass
import os

from pydantic import ValidationError

from sqlalchemy import select, update

from .auth import Credentials, hash_password, verify_password
from .database import SessionLocal, ensure_schema
from .models import TutoringJob, User


def assign_legacy_orders(db, username: str, password: str) -> int:
    credentials = Credentials(username=username, password=password)
    user = db.scalar(select(User).where(User.username == credentials.username))
    if user is None:
        user = User(username=credentials.username, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    elif not verify_password(password, user.password_hash):
        raise ValueError("初始化账号已存在且密码不匹配，未迁移任何订单")
    result = db.execute(update(TutoringJob).where(TutoringJob.owner_id.is_(None)).values(owner_id=user.id))
    db.commit()
    return result.rowcount


if __name__ == "__main__":
    ensure_schema()
    username = os.getenv("INITIAL_OWNER_USERNAME") or input("历史订单归属账号：").strip()
    password = os.getenv("INITIAL_OWNER_PASSWORD") or getpass.getpass("账号密码（至少十位）：")
    try:
        with SessionLocal() as db:
            count = assign_legacy_orders(db, username, password)
    except ValidationError:
        raise SystemExit("账号或密码格式不符合要求；账号3至40字，密码10至128字。未归属订单。") from None
    except ValueError:
        raise SystemExit("初始化账号已存在且密码不匹配，未归属订单。") from None
    print(f"账号已初始化，已归属 {count} 条历史订单。密码未写入日志。")
