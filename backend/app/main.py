import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_, select, func
from sqlalchemy.orm import Session

from . import models
from .database import engine, ensure_schema, get_db
from .ai_config import public_ai_config
from .map_config import public_map_config
from .schemas import AIConfigOut, AISearchRequest, AISearchResponse, GeocodeRequest, GeocodeResponse, ImportConfirm, ImportPreview, JobLocationUpdate, JobOut, MapConfigOut
from .services.ai_search import AIConfigurationError, AIProviderError, find_matching_jobs, select_candidate_jobs
from .services.city import normalize_city_name
from .services.distance import batch_haversine_km, distance_bounding_box
from .services.geocoding import geocode_address, forward_js_service_request
from .services.importer import preview_messages
from .auth import router as auth_router, current_user, rate_limit
from .settings import ALLOWED_ORIGINS, SYNC_WORKER_ENABLED, AI_REQUESTS_PER_MINUTE, MAP_REQUESTS_PER_MINUTE, validate_production_settings
from .sync import router as sync_router
from .sync_worker import run_worker

@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_settings()
    ensure_schema(bind=engine)
    task = asyncio.create_task(run_worker(engine)) if SYNC_WORKER_ENABLED else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="家教接单筛选平台", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=["X-Expired-Jobs-Deleted"],
)
app.include_router(auth_router)
app.include_router(sync_router)


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


def delete_expired_jobs(db: Session, owner_id: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    expired = db.scalars(select(models.TutoringJob).where(models.TutoringJob.owner_id == owner_id,
        func.coalesce(models.TutoringJob.published_at, models.TutoringJob.created_at) < cutoff)).all()
    for job in expired:
        db.delete(job)
    if expired:
        db.commit()
    return len(expired)


@app.get("/api/maps/config", response_model=MapConfigOut)
def maps_config(user: models.User = Depends(current_user)):
    return public_map_config()


@app.get("/api/maps/amap-service/{path:path}")
async def amap_js_service_proxy(path: str, request: Request, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(db, f"map:{user.id}", MAP_REQUESTS_PER_MINUTE)
    try:
        async with httpx.AsyncClient() as client:
            upstream = await forward_js_service_request(
                client,
                path,
                list(request.query_params.multi_items()),
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="不允许代理此地图服务路径") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="无法连接高德地图代理服务") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"Content-Type": upstream.headers.get("content-type", "application/json; charset=utf-8")},
    )


@app.get("/api/ai/config", response_model=AIConfigOut)
def ai_config(user: models.User = Depends(current_user)):
    return public_ai_config()


@app.post("/api/ai/search", response_model=AISearchResponse)
async def ai_search(payload: AISearchRequest, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    rate_limit(db, f"ai:{user.id}", AI_REQUESTS_PER_MINUTE)
    delete_expired_jobs(db, user.id)
    jobs = db.scalars(
        select(models.TutoringJob)
        .where(models.TutoringJob.status == "open", models.TutoringJob.owner_id == user.id)
        .order_by(models.TutoringJob.id.desc())
    ).all()
    available_jobs = [JobOut.model_validate(job).model_dump() for job in jobs]
    candidates = select_candidate_jobs(payload.query.strip(), available_jobs)
    try:
        matches = await find_matching_jobs(payload.query.strip(), candidates)
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
    city: str | None = Form(default=None, max_length=80),
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rate_limit(db, f"import:{user.id}", 20)
    if file is None and not text:
        raise HTTPException(status_code=400, detail="请上传文件或粘贴聊天文本")
    if file is not None:
        if file.filename and not file.filename.lower().endswith((".txt", ".csv")):
            raise HTTPException(status_code=400, detail="首版仅支持 TXT 和 CSV 文件")
        raw = await file.read(1_000_001)
        if len(raw) > 1_000_000:
            raise HTTPException(413, "一次最多导入 1 MB 文本，请分批导入")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="replace")
    if len(text or "") > 1_000_000:
        raise HTTPException(413, "一次最多导入一百万字符，请分批导入")
    jobs, ignored = preview_messages(text or "", source_group=source_group)
    if len(jobs) > 100:
        raise HTTPException(413, "一次最多解析 100 条订单，请分批导入")
    await geocode_jobs(jobs, city)
    return {"jobs": jobs, "ignored_lines": ignored}


async def geocode_jobs(jobs: list[dict], city: str | None = None) -> dict:
    pending = [
        job for job in jobs
        if job.get("location")
        and (job.get("location_lat") is None or job.get("location_lng") is None)
        and "线上" not in (job.get("teaching_mode") or "")
        and "线上" not in (job.get("location") or "")
    ]
    if not pending:
        return {"attempted": 0, "resolved": 0, "failed": 0, "errors": []}

    results = {"attempted": len(pending), "resolved": 0, "failed": 0, "errors": []}
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient() as client:
        async def lookup(job: dict) -> None:
            async with semaphore:
                now = datetime.now(timezone.utc)
                job["geocode_attempted_at"] = now
                result = await geocode_address(client, job.get("location"), job.get("city") or city)
                if result.resolved:
                    job["location_lat"] = result.latitude
                    job["location_lng"] = result.longitude
                    job["city"] = result.city or job.get("city") or city
                    job["geocode_status"] = "resolved"
                    job["geocode_error"] = None
                    results["resolved"] += 1
                else:
                    job["geocode_status"] = "failed"
                    job["geocode_error"] = (result.error or "地址未匹配到坐标")[:240]
                    results["failed"] += 1
                    if len(results["errors"]) < 5:
                        results["errors"].append(job["geocode_error"])

        task_jobs = {asyncio.create_task(lookup(job)): job for job in pending}
        done, unfinished = await asyncio.wait(task_jobs, timeout=12)
        for task in unfinished:
            task.cancel()
        if unfinished:
            await asyncio.gather(*unfinished, return_exceptions=True)
            for task in unfinished:
                job = task_jobs[task]
                job["geocode_status"] = "failed"
                job["geocode_error"] = "整批地址定位超过 12 秒，已结束本条定位"
                results["failed"] += 1
                if len(results["errors"]) < 5:
                    results["errors"].append(job["geocode_error"])
        # 单条意外失败不会丢失其他订单的定位结果。
        for task in done:
            try:
                task.result()
            except Exception as error:
                job = task_jobs[task]
                job["geocode_status"] = "failed"
                job["geocode_error"] = f"地址定位内部错误：{str(error)[:160]}"
                results["failed"] += 1
                if len(results["errors"]) < 5:
                    results["errors"].append(job["geocode_error"])
    return results


@app.post("/api/maps/geocode", response_model=GeocodeResponse)
async def geocode_one_address(payload: GeocodeRequest, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(db, f"map:{user.id}", MAP_REQUESTS_PER_MINUTE)
    async with httpx.AsyncClient() as client:
        result = await geocode_address(client, payload.address, payload.city)
    if not result.resolved:
        return {"geocode_status": "failed", "geocode_error": result.error}
    return {
        "location_lat": result.latitude,
        "location_lng": result.longitude,
        "city": normalize_city_name(result.city or payload.city),
        "geocode_status": "resolved",
        "geocode_error": None,
    }


@app.post("/api/jobs/geocode-missing")
async def geocode_missing_jobs(
    city: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    rate_limit(db, f"map-batch:{user.id}", 5)
    delete_expired_jobs(db, user.id)
    query = select(models.TutoringJob).where(
        models.TutoringJob.status == "open",
        models.TutoringJob.owner_id == user.id,
        models.TutoringJob.location_lat.is_(None),
        models.TutoringJob.location_lng.is_(None),
        models.TutoringJob.location.is_not(None),
    )
    if city:
        city_key = normalize_city_name(city)
        query = query.where(or_(models.TutoringJob.city == city_key, models.TutoringJob.city.is_(None)))
    jobs = db.scalars(query.order_by(models.TutoringJob.id.desc())).all()
    drafts = [
        {
            "location": job.location,
            "city": job.city,
            "location_lat": job.location_lat,
            "location_lng": job.location_lng,
            "teaching_mode": job.teaching_mode,
            "geocode_status": job.geocode_status,
            "geocode_error": None,
        }
        for job in jobs
    ]
    summary = await geocode_jobs(drafts, city)
    for job, draft in zip(jobs, drafts):
        job.location_lat = draft["location_lat"]
        job.location_lng = draft["location_lng"]
        job.city = normalize_city_name(draft.get("city"))
        job.geocode_status = draft["geocode_status"]
        job.geocode_error = draft.get("geocode_error")
        job.geocode_attempted_at = draft.get("geocode_attempted_at")
    db.commit()
    return summary


@app.post("/api/import/confirm", response_model=list[JobOut])
async def import_confirm(payload: ImportConfirm, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    rate_limit(db, f"import:{user.id}", 20)
    delete_expired_jobs(db, user.id)
    drafts = [draft.model_dump() for draft in payload.jobs]
    pending = [draft for draft in drafts if draft.get("geocode_status") == "pending"]
    if pending:
        await geocode_jobs(pending, next((draft.get("city") for draft in pending if draft.get("city")), None))
    created = []
    for draft in drafts:
        duplicate = db.scalar(
            select(models.TutoringJob).where(
                models.TutoringJob.raw_text == draft["raw_text"],
                models.TutoringJob.owner_id == user.id,
                models.TutoringJob.source_group == draft["source_group"],
            )
        )
        if duplicate:
            continue
        job = models.TutoringJob(**draft, owner_id=user.id)
        db.add(job)
        created.append(job)
    db.commit()
    for job in created:
        db.refresh(job)
    return created


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(
    response: Response,
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
    user: models.User = Depends(current_user),
) -> list[dict]:
    deleted_count = delete_expired_jobs(db, user.id)
    response.headers["X-Expired-Jobs-Deleted"] = str(deleted_count + user.expired_notice)
    if user.expired_notice:
        user.expired_notice = 0
        db.commit()
    if (origin_lat is None) != (origin_lng is None):
        raise HTTPException(status_code=400, detail="当前位置需要同时提供纬度和经度")
    if max_distance_km is not None and origin_lat is None:
        raise HTTPException(status_code=400, detail="按距离筛选前请先设置当前位置")

    query = select(models.TutoringJob).where(models.TutoringJob.status == "open", models.TutoringJob.owner_id == user.id)
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
def update_job_location(job_id: int, payload: JobLocationUpdate, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    job = db.scalar(select(models.TutoringJob).where(models.TutoringJob.id == job_id, models.TutoringJob.owner_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="未找到这条家教单")
    job.location_lat = payload.location_lat
    job.location_lng = payload.location_lng
    job.geocode_error = None
    if payload.location:
        job.location = payload.location
    if payload.city:
        job.city = normalize_city_name(payload.city)
    job.geocode_status = "manual"
    db.commit()
    db.refresh(job)
    return job


@app.patch("/api/jobs/{job_id}/status", response_model=JobOut)
def update_status(job_id: int, status: str = Query(pattern="^(open|closed)$"), db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    job = db.scalar(select(models.TutoringJob).where(models.TutoringJob.id == job_id, models.TutoringJob.owner_id == user.id))
    if not job:
        raise HTTPException(status_code=404, detail="未找到这条家教单")
    job.status = status
    db.commit()
    db.refresh(job)
    return job
