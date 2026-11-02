from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TutoringJob(Base):
    __tablename__ = "tutoring_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str | None] = mapped_column(String(40), index=True)
    grade: Mapped[str | None] = mapped_column(String(40))
    gender: Mapped[str | None] = mapped_column(String(12))
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
    raw_text: Mapped[str] = mapped_column(Text)
    source_group: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
