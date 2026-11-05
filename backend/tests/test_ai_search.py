import asyncio
import json

import httpx
import pytest

import app.services.ai_search as ai_search


def test_select_candidate_jobs_prefers_explicit_match_and_caps_candidates():
    jobs = [
        {
            "id": 1,
            "subject": "英语",
            "grade": "初二",
            "city": "北京",
            "location": "顺义区",
            "salary": 180,
            "salary_basis": "hour",
            "schedule": "周六下午",
            "requirements": "耐心负责",
        },
        {
            "id": 2,
            "subject": "数学",
            "grade": "小学六年级",
            "city": "北京",
            "location": "海淀区",
            "salary": 120,
            "salary_basis": "hour",
            "schedule": "周一晚间",
            "requirements": "细心",
        },
    ]

    matches = ai_search.select_candidate_jobs(
        "顺义附近找初中英语家教，周末上课，时薪150元以上，优先有经验且耐心。",
        jobs,
    )

    assert [job["id"] for job in matches] == [1]
    assert len(ai_search.select_candidate_jobs("找家教", jobs, limit=1)) == 1


def test_model_receives_only_bounded_summaries_without_raw_chat(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"matches":[{"id":1,"reason":"符合条件"}]}'}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(ai_search, "LLM_CHAT_COMPLETIONS_URL", "https://model.example.test/v1")
    monkeypatch.setattr(ai_search, "LLM_API_KEY", "test-only-key")
    monkeypatch.setattr(ai_search, "LLM_MODEL", "test-model")
    monkeypatch.setattr(ai_search.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    jobs = [
        {
            "id": index + 1,
            "subject": "英语",
            "grade": "初二",
            "raw_text": "完整群聊原文，不应发送",
            "source_group": "私人家教群，不应发送",
        }
        for index in range(35)
    ]

    matches = asyncio.run(ai_search.find_matching_jobs("找初中英语家教", jobs))
    sent = json.loads(captured["messages"][1]["content"])["可选订单"]

    assert len(sent) == 30
    assert matches == [{"id": 1, "reason": "符合条件"}]
    assert "原始订单" not in sent[0]
    assert "完整群聊原文，不应发送" not in captured["messages"][1]["content"]
    assert "私人家教群，不应发送" not in captured["messages"][1]["content"]


def test_model_connection_failure_is_reported_clearly(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(ai_search, "LLM_CHAT_COMPLETIONS_URL", "https://model.example.test/v1")
    monkeypatch.setattr(ai_search, "LLM_API_KEY", "test-only-key")
    monkeypatch.setattr(ai_search, "LLM_MODEL", "test-model")
    monkeypatch.setattr(ai_search.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(ai_search.AIProviderError, match="网络连通性及 TLS"):
        asyncio.run(ai_search.find_matching_jobs("找英语家教", [{"id": 1}]))
