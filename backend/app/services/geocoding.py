import re
from dataclasses import dataclass

import httpx

from ..map_config import MAP_WEB_PUBLIC_KEY, MAP_WEB_SECURITY_CODE, MAP_WEB_SERVICE_KEY

GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
PLACE_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
JS_SERVICE_BASE_URL = "https://restapi.amap.com/"
JS_SERVICE_ALLOWED_PATHS = {"v3/geocode/geo", "v3/place/text"}
LOOKUP_TIMEOUT_SECONDS = 3.5
AMAP_ERROR_GUIDANCE = {
    "10001": "Key 不正确或已过期，请检查高德控制台中的 Key。",
    "10002": "该 Key 没有此服务权限，或服务接口路径无效。",
    "10003": "已超过每日调用量，请检查高德服务配额。",
    "10004": "请求频率过高，请降低并发后重试。",
    "10005": "服务端出口 IP 不在高德 Key 的 IP 白名单中。",
    "10006": "Key 绑定域名无效，请检查控制台限制。",
    "10007": "Key 开启了签名校验，但请求签名不正确。",
    "10008": "安全码校验失败，请检查该 Key 绑定的安全配置。",
    "10009": "Key 所属平台不匹配；当前 Key 不是 Web 服务 API 类型，请另建 Web 服务 Key 并填入 MAP_WEB_SERVICE_KEY。",
    "10010": "服务端 IP 访问已超限，请按高德提示处理 IP 限流。",
    "10012": "当前 Key 没有调用该服务的权限。",
    "10041": "该 Key 的接口权限已过期。",
}
NON_RETRYABLE_AMAP_CODES = {"10001", "10002", "10003", "10004", "10005", "10006", "10007", "10008", "10009", "10010", "10012", "10013", "10041"}


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float | None = None
    longitude: float | None = None
    city: str | None = None
    formatted_address: str | None = None
    error: str | None = None

    @property
    def resolved(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def normalize_fuzzy_address(address: str) -> str:
    return re.sub(r"[，,;；\s]*(附近|周边|周围|一带|周边地区)+[，,;；\s]*$", "", address.strip()).strip()


def _response_error(payload: dict) -> str:
    code = str(payload.get("infocode") or "")
    info = str(payload.get("info") or "地图服务未返回原因")
    if len(info) > 120:
        info = info[:120]
    guidance = AMAP_ERROR_GUIDANCE.get(code)
    if code and guidance:
        return f"高德返回 {code}（{info}）：{guidance}"
    return f"高德返回 {code}: {info}" if code else f"高德返回：{info}"


def _city_component(value: object) -> str | None:
    if isinstance(value, list):
        value = next((item for item in value if item), None)
    return str(value).strip() if value else None


def _parse_location(value: object) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    try:
        longitude, latitude = (float(part) for part in value.split(",", 1))
    except (ValueError, TypeError):
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return latitude, longitude


async def _request_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    response = await client.get(url, params=params, timeout=LOOKUP_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("高德返回的数据格式不是 JSON 对象")
    return payload


def _provider_failure(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "请求高德地图超时"
    if isinstance(error, httpx.HTTPStatusError):
        return f"高德地图 HTTP 状态异常：{error.response.status_code}"
    if isinstance(error, httpx.RequestError):
        return "无法连接高德地图服务，请检查后端网络"
    return f"高德地图响应解析失败：{str(error)[:120]}"


async def geocode_address(
    client: httpx.AsyncClient,
    address: str | None,
    city: str | None = None,
    service_key: str | None = None,
) -> GeocodeResult:
    credentials: list[tuple[str, str | None]] = []
    if service_key is not None:
        if service_key.strip():
            credentials.append((service_key.strip(), None))
    else:
        if MAP_WEB_SERVICE_KEY and MAP_WEB_SERVICE_KEY != MAP_WEB_PUBLIC_KEY:
            credentials.append((MAP_WEB_SERVICE_KEY, None))
        if MAP_WEB_PUBLIC_KEY and MAP_WEB_SECURITY_CODE:
            credentials.append((MAP_WEB_PUBLIC_KEY, MAP_WEB_SECURITY_CODE))
    if not credentials:
        return GeocodeResult(error="未配置高德 Web 服务 Key，请在 backend/.env 设置 MAP_WEB_SERVICE_KEY")
    normalized = normalize_fuzzy_address(address or "")
    if not normalized:
        return GeocodeResult(error="订单没有可用于定位的上课地址")

    address_query = f"{city.strip()}{normalized}" if city and city.strip() not in normalized else normalized
    failures: list[str] = []
    for key, security_code in credentials:
        auth_params = {"key": key}
        if security_code:
            auth_params["jscode"] = security_code
        try:
            payload = await _request_json(
                client,
                GEOCODE_URL,
                {**auth_params, "address": address_query, **({"city": city} if city else {})},
            )
            geocodes = payload.get("geocodes") or []
            if str(payload.get("status")) == "1" and geocodes:
                match = geocodes[0]
                point = _parse_location(match.get("location"))
                if point:
                    component = match.get("addressComponent") or {}
                    resolved_city = _city_component(component.get("city")) or _city_component(component.get("province")) or city
                    return GeocodeResult(point[0], point[1], resolved_city, match.get("formatted_address"))
            geocode_error = _response_error(payload) if str(payload.get("status")) != "1" else "地址地理编码无结果"
            geocode_code = str(payload.get("infocode") or "")
            if geocode_code in NON_RETRYABLE_AMAP_CODES and geocode_code != "10009":
                return GeocodeResult(error=geocode_error)
            if geocode_code == "10009":
                failures.append(geocode_error)
                # A JS API key is supported through AMap's server-side JS
                # security-key proxy pattern, with jscode kept on this server.
                continue
        except Exception as error:  # provider failures should not abort importing other orders
            return GeocodeResult(error=_provider_failure(error))

        # POI search handles abbreviated campus, estate, and landmark names.
        try:
            params = {**auth_params, "keywords": normalized, "offset": 1, "page": 1, "extensions": "all"}
            if city:
                params.update({"city": city, "citylimit": "true"})
            payload = await _request_json(client, PLACE_SEARCH_URL, params)
            pois = payload.get("pois") or []
            if str(payload.get("status")) == "1" and pois:
                poi = pois[0]
                point = _parse_location(poi.get("location"))
                if point:
                    resolved_city = poi.get("cityname") or poi.get("pname") or city
                    return GeocodeResult(point[0], point[1], resolved_city, poi.get("address") or poi.get("name"))
            poi_error = _response_error(payload) if str(payload.get("status")) != "1" else "POI 搜索无结果"
            failures.append(f"{geocode_error}；{poi_error}")
            code = str(payload.get("infocode") or "")
            if code in NON_RETRYABLE_AMAP_CODES and code != "10009":
                return GeocodeResult(error=failures[-1])
        except Exception as error:  # provider failures should not abort importing other orders
            failures.append(f"{geocode_error}；POI 搜索失败：{_provider_failure(error)}")
            return GeocodeResult(error=failures[-1])
    return GeocodeResult(error="；".join(failures[-2:]) or "地址没有匹配到坐标")


async def forward_js_service_request(
    client: httpx.AsyncClient,
    path: str,
    params: list[tuple[str, str]],
    security_code: str | None = None,
) -> httpx.Response:
    if path not in JS_SERVICE_ALLOWED_PATHS:
        raise ValueError("不允许代理此地图服务路径")
    code = (security_code if security_code is not None else MAP_WEB_SECURITY_CODE).strip()
    if not code:
        raise RuntimeError("未配置 MAP_WEB_SECURITY_CODE")
    safe_params = [(name, value) for name, value in params if name.lower() != "jscode"]
    safe_params.append(("jscode", code))
    return await client.get(f"{JS_SERVICE_BASE_URL}{path}", params=safe_params, timeout=10)
