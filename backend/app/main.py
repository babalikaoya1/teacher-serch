from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models
from .database import engine, ensure_schema, get_db
from .ai_config import public_ai_config
from .map_config import public_map_config
from .schemas import AIConfigOut, AISearchRequest, AISearchResponse, ImportConfirm, ImportPreview, JobLocationUpdate, JobOut, MapConfigOut
from .services.ai_search import AIConfigurationError, AIProviderError, find_matching_jobs
from .services.city import normalize_city_name
from .services.distance import batch_haversine_km, distance_bounding_box
from .services.importer import preview_messages


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema(bind=engine)
    yield


app = FastAPI(title="家教接单筛选平台", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/maps/config", response_model=MapConfigOut)
def maps_config():
    return public_map_config()


@app.get("/api/ai/config", response_model=AIConfigOut)
def ai_config():
    return public_ai_config()


@app.post("/api/ai/search", response_model=AISearchResponse)
async def ai_search(payload: AISearchRequest, db: Session = Depends(get_db)):
    jobs = db.scalars(
        select(models.TutoringJob)
        .where(models.TutoringJob.status == "open")
        .order_by(models.TutoringJob.id.desc())
        .limit(300)
    ).all()
    available_jobs = [JobOut.model_validate(job).model_dump() for job in jobs]
    try:
        matches = await find_matching_jobs(payload.query.strip(), available_jobs)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    by_id = {job["id"]: job for job in available_jobs}
    return {"matches": [{"job": by_id[item["id"]], "reason": item["reason"]} for item in matches]}


@app.post("/api/import/preview", response_model=ImportPreview)
async def import_preview(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    source_group: str | None = Form(default=None),
):
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
    jobs, ignored = preview_messages(text or "", source_group=source_group)
    return {"jobs": jobs, "ignored_lines": ignored}


@app.post("/api/import/confirm", response_model=list[JobOut])
def import_confirm(payload: ImportConfirm, db: Session = Depends(get_db)):
    created = []
    for draft in payload.jobs:
        duplicate = db.scalar(
            select(models.TutoringJob).where(
                models.TutoringJob.raw_text == draft.raw_text,
                models.TutoringJob.source_group == draft.source_group,
            )
        )
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
    source_group: str | None = None,
    city: str | None = Query(default=None, max_length=80),
    min_salary: float | None = Query(default=None, ge=0),
    max_salary: float | None = Query(default=None, ge=0),
    origin_lat: float | None = Query(default=None, ge=-90, le=90),
    origin_lng: float | None = Query(default=None, ge=-180, le=180),
    max_distance_km: float | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    if (origin_lat is None) != (origin_lng is None):
        raise HTTPException(status_code=400, detail="当前位置需要同时提供纬度和经度")
    if max_distance_km is not None and origin_lat is None:
        raise HTTPException(status_code=400, detail="按距离筛选前请先设置当前位置")

    query = select(models.TutoringJob).where(models.TutoringJob.status == "open")
    if subject:
        query = query.where(models.TutoringJob.subject.contains(subject))
    if location:
        query = query.where(models.TutoringJob.location.contains(location))
    if source_group:
        query = query.where(models.TutoringJob.source_group.contains(source_group))
    city_key = normalize_city_name(city)
    if city_key:
        query = query.where(models.TutoringJob.city == city_key)
    if min_salary is not None:
        query = query.where(
            models.TutoringJob.salary >= min_salary,
            or_(models.TutoringJob.salary_basis == "hour", models.TutoringJob.salary_basis.is_(None)),
        )
    if max_salary is not None:
        query = query.where(
            models.TutoringJob.salary <= max_salary,
            or_(models.TutoringJob.salary_basis == "hour", models.TutoringJob.salary_basis.is_(None)),
        )
    if max_distance_km is not None and origin_lat is not None and origin_lng is not None:
        latitude_delta, longitude_delta = distance_bounding_box(origin_lat, max_distance_km)
        query = query.where(
            models.TutoringJob.location_lat.between(max(-90, origin_lat - latitude_delta), min(90, origin_lat + latitude_delta)),
            or_(models.TutoringJob.teaching_mode.is_(None), ~models.TutoringJob.teaching_mode.contains("线上")),
            or_(models.TutoringJob.location.is_(None), ~models.TutoringJob.location.contains("线上")),
        )
        min_lng = origin_lng - longitude_delta
        max_lng = origin_lng + longitude_delta
        if min_lng < -180:
            query = query.where(or_(models.TutoringJob.location_lng >= min_lng + 360, models.TutoringJob.location_lng <= max_lng))
        elif max_lng > 180:
            query = query.where(or_(models.TutoringJob.location_lng >= min_lng, models.TutoringJob.location_lng <= max_lng - 360))
        else:
            query = query.where(models.TutoringJob.location_lng.between(min_lng, max_lng))
    jobs = db.scalars(query.order_by(models.TutoringJob.id.desc())).all()
    distances = batch_haversine_km(origin_lat, origin_lng, jobs) if origin_lat is not None and origin_lng is not None else {}
    results = []
    for job in jobs:
        item = JobOut.model_validate(job).model_dump()
        if job.id in distances:
            distance = distances[job.id]
            item["distance_km"] = round(distance, 2)
            is_online = "线上" in (job.teaching_mode or "") or "线上" in (job.location or "")
            if max_distance_km is not None and (is_online or distance > max_distance_km):
                continue
        elif max_distance_km is not None:
            continue
        results.append(item)
    return results


@app.patch("/api/jobs/{job_id}/location", response_model=JobOut)
def update_job_location(job_id: int, payload: JobLocationUpdate, db: Session = Depends(get_db)):
    job = db.get(models.TutoringJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到这条家教单")
    job.location_lat = payload.location_lat
    job.location_lng = payload.location_lng
    if payload.location:
        job.location = payload.location
    if payload.city:
        job.city = normalize_city_name(payload.city)
    job.geocode_status = "manual"
    db.commit()
    db.refresh(job)
    return job


@app.patch("/api/jobs/{job_id}/status", response_model=JobOut)
def update_status(job_id: int, status: str = Query(pattern="^(open|closed)$"), db: Session = Depends(get_db)):
    job = db.get(models.TutoringJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到这条家教单")
    job.status = status
    db.commit()
    db.refresh(job)
    return job
