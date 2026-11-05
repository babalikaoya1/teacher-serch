import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services.geocoding import GeocodeResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.main as main

    test_engine = create_engine(f"sqlite:///{tmp_path / 'api-test.db'}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "SYNC_WORKER_ENABLED", False)

    async def fake_geocode_address(client, address, city=None, service_key=None):
        return GeocodeResult(error="模拟地址无结果")

    monkeypatch.setattr(main, "geocode_address", fake_geocode_address)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/register", json={"username": "测试账号", "password": "测试专用密码123456"})
        assert response.status_code == 201
        yield test_client
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_import_preview_confirm_duplicate_and_filter(client):
    text = "家教单验收专用：初中数学家教，周末上课，薪资 180元/小时，地址在海淀区"
    preview = client.post("/api/import/preview", data={"text": text, "source_group": "测试家教群"})
    assert preview.status_code == 200
    draft = preview.json()["jobs"][0]
    assert draft["subject"] == "数学"
    assert draft["location"] == "海淀区"
    assert draft["source_group"] == "测试家教群"
    draft["location_lat"] = 39.9
    draft["location_lng"] = 116.4
    draft["geocode_status"] = "resolved"

    first = client.post("/api/import/confirm", json={"jobs": [draft]})
    assert first.status_code == 200
    assert len(first.json()) == 1
    assert first.json()[0]["geocode_status"] == "resolved"
    second = client.post("/api/import/confirm", json={"jobs": [draft]})
    assert second.json() == []

    other_group = {**draft, "source_group": "另一个家教群"}
    other_source = client.post("/api/import/confirm", json={"jobs": [other_group]})
    assert len(other_source.json()) == 1

    results = client.get("/api/jobs", params={
        "subject": "数学",
        "location": "海淀",
        "source_group": "测试家教群",
        "min_salary": 150,
        "origin_lat": 39.9,
        "origin_lng": 116.4,
        "max_distance_km": 1,
    })
    assert results.status_code == 200
    assert len(results.json()) == 1
    assert results.json()[0]["raw_text"] == text
    assert results.json()[0]["distance_km"] == 0

    missing_origin = client.get("/api/jobs", params={"max_distance_km": 5})
    assert missing_origin.status_code == 400


def test_maps_config_exposes_only_the_web_sdk_values(client, monkeypatch):
    import app.map_config as map_config

    monkeypatch.setattr(map_config, "MAP_WEB_SDK_URL", "https://maps.example.test/loader.js")
    monkeypatch.setattr(map_config, "MAP_WEB_PUBLIC_KEY", "public-test-key")
    monkeypatch.setattr(map_config, "MAP_WEB_SERVICE_KEY", "private-service-test-key")
    monkeypatch.setattr(map_config, "MAP_WEB_SECURITY_CODE", "private-security-test-code")
    response = client.get("/api/maps/config")
    assert response.status_code == 200
    assert response.json()["sdk_url"] == "https://maps.example.test/loader.js"
    assert response.json()["public_key"] == "public-test-key"
    assert response.json()["web_sdk_configured"] is True
    assert response.json()["server_geocoding_configured"] is True
    assert response.json()["js_security_proxy_configured"] is True
    assert response.json()["js_service_proxy_url"] == "/api/maps/amap-service"
    assert "server_api_key" not in response.json()
    assert "MAP_WEB_SERVICE_KEY" not in response.text
    assert "private-service-test-key" not in response.text
    assert "private-security-test-code" not in response.text


def test_distance_filter_returns_only_orders_within_radius_and_hourly_salary(client):
    orders = [
        {"subject": "数学", "city": "北京市", "location": "海淀区", "teaching_mode": "线下", "salary": 150, "salary_basis": "hour", "raw_text": "近距离时薪订单"},
        {"subject": "数学", "city": "北京", "location": "海淀区", "teaching_mode": "线下", "salary": 180, "salary_basis": "hour", "raw_text": "远距离时薪订单"},
        {"subject": "数学", "city": "北京", "location": "海淀区", "teaching_mode": "线下", "salary": 750, "salary_basis": "week", "raw_text": "周薪订单"},
        {"subject": "数学", "city": "北京", "location": "线上", "teaching_mode": "线上", "salary": 200, "salary_basis": "hour", "raw_text": "线上订单"},
        {"subject": "数学", "city": "成都", "location": "市中心", "teaching_mode": "线下", "salary": 160, "salary_basis": "hour", "raw_text": "其他城市同坐标订单"},
    ]
    for order in orders:
        order["location_lat"] = 39.9
        order["location_lng"] = 116.4
    orders[1]["location_lat"] = 39.91
    saved = client.post("/api/import/confirm", json={"jobs": orders})
    assert saved.status_code == 200

    response = client.get("/api/jobs", params={
        "min_salary": 100,
        "max_distance_km": 1,
        "origin_lat": 39.9,
        "origin_lng": 116.4,
        "city": "北京市",
    })
    assert response.status_code == 200
    assert [job["raw_text"] for job in response.json()] == ["近距离时薪订单"]
    assert response.json()[0]["distance_km"] == 0


def test_existing_order_location_can_be_saved_and_used_for_distance(client):
    draft = {"city": "北京市", "location": "海淀区", "raw_text": "旧订单，等待补坐标"}
    saved = client.post("/api/import/confirm", json={"jobs": [draft]}).json()[0]
    update = client.patch(f"/api/jobs/{saved['id']}/location", json={
        "location_lat": 39.9,
        "location_lng": 116.4,
        "location": "海淀区某地",
        "city": "北京",
    })
    assert update.status_code == 200
    assert update.json()["location"] == "海淀区某地"
    assert update.json()["city"] == "北京"

    results = client.get("/api/jobs", params={
        "origin_lat": 39.9,
        "origin_lng": 116.4,
        "max_distance_km": 0.5,
    })
    assert len(results.json()) == 1
    assert results.json()[0]["distance_km"] == 0


def test_geocoding_timeout_does_not_block_importing_orders(client):
    orders = [
        {"location": "海淀五棵松附近", "raw_text": "地址定位超时订单", "geocode_status": "failed"},
        {"location": "顺义区某小区", "raw_text": "正常订单", "location_lat": 40.1, "location_lng": 116.6, "geocode_status": "resolved"},
    ]
    response = client.post("/api/import/confirm", json={"jobs": orders})
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["geocode_status"] == "failed"
    assert response.json()[0]["location_lat"] is None
    assert response.json()[1]["location_lat"] == 40.1


def test_import_preview_geocodes_server_side_and_distance_filter_uses_saved_coordinates(client, monkeypatch):
    import app.main as main

    async def successful_geocode(client, address, city=None, service_key=None):
        return GeocodeResult(39.9, 116.4, "北京市", "北京市海淀区五棵松")

    monkeypatch.setattr(main, "geocode_address", successful_geocode)
    preview = client.post("/api/import/preview", data={
        "text": "初中数学家教，周末上课，薪资 150元/小时，地址在海淀区五棵松",
        "city": "北京市",
    })
    assert preview.status_code == 200
    draft = preview.json()["jobs"][0]
    assert draft["location_lat"] == 39.9
    assert draft["location_lng"] == 116.4
    assert draft["geocode_status"] == "resolved"

    saved = client.post("/api/import/confirm", json={"jobs": [draft]}).json()[0]
    assert saved["location_lat"] == 39.9
    results = client.get("/api/jobs", params={
        "city": "北京市", "origin_lat": 39.9, "origin_lng": 116.4, "max_distance_km": 5,
    })
    assert len(results.json()) == 1
    assert results.json()[0]["distance_km"] == 0


def test_one_failed_geocode_does_not_block_other_import_preview_orders(client, monkeypatch):
    import app.main as main

    async def mixed_geocode(client, address, city=None, service_key=None):
        if "海淀" in address:
            return GeocodeResult(error="模拟高德地址无结果")
        return GeocodeResult(39.9, 116.4, "北京市", "北京市朝阳区")

    monkeypatch.setattr(main, "geocode_address", mixed_geocode)
    response = client.post("/api/import/preview", data={
        "city": "北京市",
        "text": "初中数学家教\n地址：海淀区五棵松\n\n初中英语家教\n地址：朝阳区望京",
    })
    assert response.status_code == 200
    drafts = response.json()["jobs"]
    assert len(drafts) == 2
    assert [draft["geocode_status"] for draft in drafts] == ["failed", "resolved"]
    assert "模拟高德地址无结果" in drafts[0]["geocode_error"]
    assert drafts[1]["location_lat"] == 39.9


def test_distance_search_backfills_existing_missing_coordinates(client, monkeypatch):
    import app.main as main

    saved = client.post("/api/import/confirm", json={"jobs": [{
        "city": "北京市", "location": "海淀五棵松附近", "raw_text": "历史订单待补坐标",
    }]}).json()[0]
    async def successful_geocode(client, address, city=None, service_key=None):
        assert city == "北京市" or city == "北京"
        return GeocodeResult(39.9, 116.4, "北京市", "北京市海淀区五棵松")

    monkeypatch.setattr(main, "geocode_address", successful_geocode)
    backfill = client.post("/api/jobs/geocode-missing", params={"city": "北京市"})
    assert backfill.status_code == 200
    assert backfill.json()["resolved"] == 1
    filtered = client.get("/api/jobs", params={
        "city": "北京市", "origin_lat": 39.9, "origin_lng": 116.4, "max_distance_km": 5,
    })
    assert [job["id"] for job in filtered.json()] == [saved["id"]]


def test_orders_are_appended_and_expired_orders_are_deleted_with_notice(client):
    first = client.post("/api/import/confirm", json={"jobs": [{"raw_text": "第一条独立订单"}]}).json()
    second = client.post("/api/import/confirm", json={"jobs": [{"raw_text": "第二条独立订单"}]}).json()
    assert first[0]["id"] != second[0]["id"]
    assert first[0]["created_at"]

    import app.main as main
    from sqlalchemy import text

    with main.engine.begin() as connection:
        connection.execute(text("UPDATE tutoring_jobs SET created_at = datetime('now', '-4 days') WHERE id = :job_id"), {"job_id": first[0]["id"]})
    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert response.headers["X-Expired-Jobs-Deleted"] == "1"
    assert [job["raw_text"] for job in response.json()] == ["第二条独立订单"]


def test_ai_search_returns_matched_database_job(client, monkeypatch):
    import app.main as main

    async def fake_find_matching_jobs(query, jobs):
        assert query == "順義附近的初中英語家教"
        assert len(jobs) == 1
        return [{"id": jobs[0]["id"], "reason": "區域、年級和科目符合"}]

    monkeypatch.setattr(main, "find_matching_jobs", fake_find_matching_jobs)
    draft = {
        "subject": "英語",
        "grade": "初二",
        "location": "順義區",
        "raw_text": "初二英語，順義區，週末上課",
        "source_group": "測試群",
    }
    saved = client.post("/api/import/confirm", json={"jobs": [draft]}).json()[0]

    response = client.post("/api/ai/search", json={"query": "順義附近的初中英語家教"})
    assert response.status_code == 200
    assert response.json()["matches"] == [{"job": saved, "reason": "區域、年級和科目符合"}]


def test_ai_search_reports_missing_server_configuration(client, monkeypatch):
    from app.services import ai_search

    monkeypatch.setattr(ai_search, "LLM_CHAT_COMPLETIONS_URL", "")
    monkeypatch.setattr(ai_search, "LLM_API_KEY", "")
    monkeypatch.setattr(ai_search, "LLM_MODEL", "")

    response = client.post("/api/ai/search", json={"query": "找初中英语家教"})
    assert response.status_code == 503
    assert "backend/.env" in response.json()["detail"]
