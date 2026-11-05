import asyncio

import httpx

from app.services.geocoding import forward_js_service_request, geocode_address


def make_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_exact_address_geocoding_returns_amap_coordinate():
    def handler(request):
        assert request.url.path.endswith("/v3/geocode/geo")
        assert request.url.params["address"] == "北京市海淀区五棵松"
        return httpx.Response(200, json={
            "status": "1",
            "geocodes": [{
                "location": "116.275,39.905",
                "formatted_address": "北京市海淀区五棵松",
                "addressComponent": {"city": "北京市"},
            }],
        })

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀区五棵松附近", "北京市", "server-test-key")

    result = asyncio.run(run())
    assert result.resolved is True
    assert result.latitude == 39.905
    assert result.longitude == 116.275
    assert result.city == "北京市"


def test_fuzzy_address_falls_back_to_poi_search():
    def handler(request):
        if request.url.path.endswith("/geocode/geo"):
            return httpx.Response(200, json={"status": "1", "geocodes": []})
        assert request.url.path.endswith("/place/text")
        assert request.url.params["citylimit"] == "true"
        return httpx.Response(200, json={
            "status": "1",
            "pois": [{"location": "116.275,39.905", "cityname": "北京市", "address": "海淀区五棵松"}],
        })

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀五棵松附近", "北京市", "server-test-key")

    result = asyncio.run(run())
    assert result.resolved is True
    assert result.formatted_address == "海淀区五棵松"


def test_provider_error_and_no_result_are_explained_without_exposing_key():
    def handler(request):
        return httpx.Response(200, json={"status": "0", "infocode": "10001", "info": "INVALID_USER_KEY"})

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀五棵松", "北京市", "do-not-return-this-key")

    result = asyncio.run(run())
    assert result.resolved is False
    assert "10001" in result.error
    assert "INVALID_USER_KEY" in result.error
    assert "Key 不正确或已过期" in result.error
    assert "do-not-return-this-key" not in result.error


def test_js_key_platform_mismatch_tells_user_to_create_web_service_key():
    def handler(request):
        return httpx.Response(200, json={"status": "0", "infocode": "10009", "info": "USERKEY_PLAT_NOMATCH"})

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀五棵松", "北京市", "js-platform-key")

    result = asyncio.run(run())
    assert result.resolved is False
    assert "不是 Web 服务 API 类型" in result.error
    assert "MAP_WEB_SERVICE_KEY" in result.error


def test_js_key_and_security_code_fallback_stays_server_side(monkeypatch):
    import app.services.geocoding as service

    monkeypatch.setattr(service, "MAP_WEB_SERVICE_KEY", "wrong-platform-service-key")
    monkeypatch.setattr(service, "MAP_WEB_PUBLIC_KEY", "valid-js-key")
    monkeypatch.setattr(service, "MAP_WEB_SECURITY_CODE", "server-only-security-code")

    def handler(request):
        if request.url.params["key"] == "wrong-platform-service-key":
            return httpx.Response(200, json={"status": "0", "infocode": "10009", "info": "USERKEY_PLAT_NOMATCH"})
        assert request.url.params["key"] == "valid-js-key"
        assert request.url.params["jscode"] == "server-only-security-code"
        return httpx.Response(200, json={
            "status": "1",
            "geocodes": [{"location": "116.275,39.905", "addressComponent": {"city": "北京市"}}],
        })

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀五棵松", "北京市")

    result = asyncio.run(run())
    assert result.resolved is True
    assert result.latitude == 39.905
    assert "server-only-security-code" not in (result.error or "")


def test_provider_no_match_reports_that_address_and_poi_search_found_nothing():
    def handler(request):
        return httpx.Response(200, json={"status": "1", "geocodes": [], "pois": []})

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "无匹配地点", "北京市", "server-test-key")

    result = asyncio.run(run())
    assert result.resolved is False
    assert "地址地理编码无结果" in result.error
    assert "POI 搜索无结果" in result.error


def test_timeout_is_recorded_and_does_not_raise_to_importer():
    def handler(request):
        raise httpx.ReadTimeout("provider timeout", request=request)

    async def run():
        async with make_client(handler) as client:
            return await geocode_address(client, "海淀五棵松", "北京市", "server-test-key")

    result = asyncio.run(run())
    assert result.resolved is False
    assert "超时" in result.error


def test_missing_server_key_returns_actionable_configuration_error():
    async def run():
        async with make_client(lambda request: httpx.Response(500)) as client:
            return await geocode_address(client, "海淀五棵松", service_key="")

    result = asyncio.run(run())
    assert result.resolved is False
    assert "MAP_WEB_SERVICE_KEY" in result.error


def test_js_map_service_proxy_injects_server_security_code_without_returning_it():
    def handler(request):
        assert request.url.host == "restapi.amap.com"
        assert request.url.params["jscode"] == "server-only-security-code"
        assert request.url.params["key"] == "public-js-key"
        return httpx.Response(200, json={"status": "1"})

    async def run():
        async with make_client(handler) as client:
            return await forward_js_service_request(
                client,
                "v3/geocode/geo",
                [("key", "public-js-key"), ("jscode", "untrusted-client-code")],
                "server-only-security-code",
            )

    response = asyncio.run(run())
    assert response.json() == {"status": "1"}
    assert "server-only-security-code" not in response.text
