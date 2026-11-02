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
