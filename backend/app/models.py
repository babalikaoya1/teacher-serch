from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TutoringJob(Base):
    __tablename__ = "tutoring_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str | None] = mapped_column(String(40), index=True)
    grade: Mapped[str | None] = mapped_column(String(40))
    location: Mapped[str | None] = mapped_column(String(120), index=True)
    salary: Mapped[float | None] = mapped_column(Float, index=True)
    salary_unit: Mapped[str | None] = mapped_column(String(20))
    schedule: Mapped[str | None] = mapped_column(String(120))
    raw_text: Mapped[str] = mapped_column(Text)
    source_group: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
