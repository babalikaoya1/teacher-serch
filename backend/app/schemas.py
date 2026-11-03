from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .services.city import normalize_city_name


class JobDraft(BaseModel):
    subject: str | None = None
    grade: str | None = None
    gender: str | None = None
    city: str | None = Field(default=None, max_length=80)
    location: str | None = None
    teaching_mode: str | None = None
    salary: float | None = Field(default=None, ge=0)
    salary_unit: str | None = None
    salary_basis: str | None = None
    salary_is_minimum: bool = False
    schedule: str | None = None
    order_code: str | None = None
    student_notes: str | None = None
    requirements: str | None = None
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lng: float | None = Field(default=None, ge=-180, le=180)
    geocode_status: Literal["pending", "resolved", "manual", "failed"] = "pending"
    raw_text: str = Field(min_length=1, max_length=10000)
    source_group: str | None = None

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.location_lat is None) != (self.location_lng is None):
            raise ValueError("地点坐标需要同时提供纬度和经度")
        return self

    @model_validator(mode="before")
    @classmethod
    def normalize_city_field(cls, values):
        if isinstance(values, dict) and "city" in values:
            values = {**values, "city": normalize_city_name(values.get("city"))}
        return values


class MapConfigOut(BaseModel):
    sdk_url: str | None = None
    public_key: str | None = None
    web_sdk_configured: bool
    geocoding_api_configured: bool
    routing_api_configured: bool
    provider_name: str | None = None


class AIConfigOut(BaseModel):
    configured: bool
    model: str | None = None


class AISearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)


class JobLocationUpdate(BaseModel):
    location_lat: float = Field(ge=-90, le=90)
    location_lng: float = Field(ge=-180, le=180)
    location: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=80)

    @model_validator(mode="before")
    @classmethod
    def normalize_city_field(cls, values):
        if isinstance(values, dict) and "city" in values:
            values = {**values, "city": normalize_city_name(values.get("city"))}
        return values


class ImportPreview(BaseModel):
    jobs: list[JobDraft]
    ignored_lines: int


class JobOut(JobDraft):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    distance_km: float | None = None


class AIMatch(BaseModel):
    job: JobOut
    reason: str


class AISearchResponse(BaseModel):
    matches: list[AIMatch]


class ImportConfirm(BaseModel):
    jobs: list[JobDraft]
