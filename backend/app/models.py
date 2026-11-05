from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TutoringJob(Base):
    __tablename__ = "tutoring_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_message_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_part: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("source_message_id", "source_part", name="uq_job_message_part"),)
    subject: Mapped[str | None] = mapped_column(String(40), index=True)
    grade: Mapped[str | None] = mapped_column(String(40))
    gender: Mapped[str | None] = mapped_column(String(12))
    city: Mapped[str | None] = mapped_column(String(80), index=True)
    location: Mapped[str | None] = mapped_column(String(120), index=True)
    teaching_mode: Mapped[str | None] = mapped_column(String(20))
    salary: Mapped[float | None] = mapped_column(Float, index=True)
    salary_unit: Mapped[str | None] = mapped_column(String(20))
    salary_basis: Mapped[str | None] = mapped_column(String(20))
    salary_is_minimum: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule: Mapped[str | None] = mapped_column(String(120))
    order_code: Mapped[str | None] = mapped_column(String(80))
    student_notes: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    location_lat: Mapped[float | None] = mapped_column(Float)
    location_lng: Mapped[float | None] = mapped_column(Float)
    geocode_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    geocode_error: Mapped[str | None] = mapped_column(String(240))
    geocode_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_text: Mapped[str] = mapped_column(Text)
    source_group: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    expired_notice: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PairingCode(Base):
    __tablename__ = "pairing_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncDevice(Base):
    __tablename__ = "sync_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    detail: Mapped[str | None] = mapped_column(String(240))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncSource(Base):
    __tablename__ = "sync_sources"
    __table_args__ = (UniqueConstraint("device_id", "external_key", name="uq_source_device_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    device_id: Mapped[str] = mapped_column(String(36), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    city: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="paused")
    detail: Mapped[str | None] = mapped_column(String(240))
    earliest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncMessage(Base):
    __tablename__ = "sync_messages"
    __table_args__ = (UniqueConstraint("source_id", "message_key", name="uq_sync_source_message"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    message_key: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(String(120))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    detail: Mapped[str | None] = mapped_column(String(240))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_drafts: Mapped[str | None] = mapped_column(Text)
