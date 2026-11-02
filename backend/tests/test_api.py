import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.main as main

    test_engine = create_engine(f"sqlite:///{tmp_path / 'api-test.db'}", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(main, "engine", test_engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
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

    first = client.post("/api/import/confirm", json={"jobs": [draft]})
    assert first.status_code == 200
    assert len(first.json()) == 1
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


def test_maps_config_does_not_return_credentials(client):
    response = client.get("/api/maps/config")
    assert response.status_code == 200
    assert "web_public_key" not in response.json()
    assert "server_api_key" not in response.json()
