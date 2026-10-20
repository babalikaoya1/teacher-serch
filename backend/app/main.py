from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import Base, engine, get_db
from .schemas import ImportConfirm, ImportPreview, JobDraft, JobOut
from .services.importer import preview_messages


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="家教接单筛选平台", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/import/preview", response_model=ImportPreview)
async def import_preview(file: UploadFile | None = File(default=None), text: str | None = Form(default=None)):
    if file is None and not text:
        raise HTTPException(status_code=400, detail="请上传文件或粘贴聊天文本")
    if file is not None:
        if file.filename and not file.filename.lower().endswith((".txt", ".csv")):
            raise HTTPException(status_code=400, detail="首版仅支持 TXT 和 CSV 文件")
        raw = await file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="replace")
    jobs, ignored = preview_messages(text or "")
    return {"jobs": jobs, "ignored_lines": ignored}


@app.post("/api/import/confirm", response_model=list[JobOut])
def import_confirm(payload: ImportConfirm, db: Session = Depends(get_db)):
    created = []
    for draft in payload.jobs:
        duplicate = db.scalar(select(models.TutoringJob).where(models.TutoringJob.raw_text == draft.raw_text))
        if duplicate:
            continue
        job = models.TutoringJob(**draft.model_dump())
        db.add(job)
        created.append(job)
    db.commit()
    for job in created:
        db.refresh(job)
    return created


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(
    subject: str | None = None,
    location: str | None = None,
    min_salary: float | None = Query(default=None, ge=0),
    max_salary: float | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
):
    query = select(models.TutoringJob).where(models.TutoringJob.status == "open")
    if subject:
        query = query.where(models.TutoringJob.subject.contains(subject))
    if location:
        query = query.where(models.TutoringJob.location.contains(location))
    if min_salary is not None:
        query = query.where(models.TutoringJob.salary >= min_salary)
    if max_salary is not None:
        query = query.where(models.TutoringJob.salary <= max_salary)
    return db.scalars(query.order_by(models.TutoringJob.id.desc())).all()


@app.patch("/api/jobs/{job_id}/status", response_model=JobOut)
def update_status(job_id: int, status: str = Query(pattern="^(open|closed)$"), db: Session = Depends(get_db)):
    job = db.get(models.TutoringJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到这条家教单")
    job.status = status
    db.commit()
    db.refresh(job)
    return job
