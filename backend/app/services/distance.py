from math import asin, cos, radians, sin, sqrt


def haversine_km(origin_lat: float, origin_lng: float, target_lat: float, target_lng: float) -> float:
    """计算两坐标间的球面直线距离，结果单位为公里。"""
    earth_radius_km = 6371.0088
    lat_delta = radians(target_lat - origin_lat)
    lng_delta = radians(target_lng - origin_lng)
    origin_lat_rad = radians(origin_lat)
    target_lat_rad = radians(target_lat)
    value = sin(lat_delta / 2) ** 2 + cos(origin_lat_rad) * cos(target_lat_rad) * sin(lng_delta / 2) ** 2
    return earth_radius_km * 2 * asin(sqrt(min(1.0, value)))


def distance_bounding_box(origin_lat: float, radius_km: float) -> tuple[float, float]:
    latitude_delta = radius_km / 110.574
    maximum_absolute_latitude = min(90.0, abs(origin_lat) + latitude_delta)
    longitude_scale = max(abs(cos(radians(maximum_absolute_latitude))), 1e-6)
    longitude_delta = min(180.0, radius_km / (111.320 * longitude_scale))
    return latitude_delta, longitude_delta


def batch_haversine_km(origin_lat: float, origin_lng: float, jobs) -> dict[int, float]:
    return {
        job.id: haversine_km(origin_lat, origin_lng, job.location_lat, job.location_lng)
        for job in jobs
        if job.location_lat is not None and job.location_lng is not None
    }
