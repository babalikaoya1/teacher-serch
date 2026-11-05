"""将本地 SQLite 快照迁入空的 PostgreSQL，不修改源数据库或覆盖目标数据。"""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile

from sqlalchemy import Integer, create_engine, func, select, text

from . import models
from .database import Base, ensure_schema


def copy_into_empty_database(source, target):
    ensure_schema(target)
    counts = {}
    with source.connect() as reader, target.begin() as writer:
        for table in Base.metadata.sorted_tables:
            if writer.scalar(select(func.count()).select_from(table)):
                raise ValueError("目标数据库已有数据，已停止迁移；请使用独立空数据库")
        for table in Base.metadata.sorted_tables:
            rows = reader.execute(select(table)).mappings().all()
            if rows:
                writer.execute(table.insert(), [dict(row) for row in rows])
            counts[table.name] = len(rows)
            if target.dialect.name == "postgresql" and "id" in table.c and isinstance(table.c.id.type, Integer):
                sequence = writer.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table.name})
                maximum = max((row["id"] for row in rows), default=0)
                if sequence:
                    writer.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :used)"),
                        {"sequence": sequence, "value": max(maximum, 1), "used": maximum > 0})
    return counts


def migrate_sqlite(source_path, target_url):
    source_path = Path(source_path).resolve(strict=True)
    if not target_url.startswith("postgresql"):
        raise ValueError("迁移目标必须是 PostgreSQL；连接地址通过 DATABASE_URL 环境变量配置")
    # 在临时副本上补字段，原文件以只读方式打开。
    with tempfile.TemporaryDirectory(prefix="teacher-migration-") as directory:
        snapshot = Path(directory) / "snapshot.db"
        with sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True) as original, sqlite3.connect(snapshot) as backup:
            original.backup(backup)
        source = create_engine(f"sqlite:///{snapshot.as_posix()}")
        target = create_engine(target_url)
        try:
            ensure_schema(source)
            return copy_into_empty_database(source, target)
        finally:
            source.dispose()
            target.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将 SQLite 副本迁移到空的 PostgreSQL 数据库")
    parser.add_argument("--source", required=True, help="SQLite 文件路径；迁移期间请停止原服务写入")
    args = parser.parse_args()
    try:
        counts = migrate_sqlite(args.source, os.getenv("DATABASE_URL", ""))
    except Exception as error:
        # 数据库连接异常可能包含凭证，仅输出类别和人工排查入口。
        detail = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}：请检查源文件权限、目标连接配置及空库条件"
        raise SystemExit(f"迁移未完成：{detail}") from None
    print("迁移完成，各表记录数：", counts)
