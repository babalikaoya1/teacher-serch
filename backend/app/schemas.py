from pydantic import BaseModel, ConfigDict, Field


class JobDraft(BaseModel):
    subject: str | None = None
    grade: str | None = None
    location: str | None = None
    salary: float | None = Field(default=None, ge=0)
    salary_unit: str | None = None
    schedule: str | None = None
    raw_text: str = Field(min_length=1, max_length=10000)
    source_group: str | None = None


class ImportPreview(BaseModel):
    jobs: list[JobDraft]
    ignored_lines: int


class JobOut(JobDraft):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str


class ImportConfirm(BaseModel):
    jobs: list[JobDraft]
