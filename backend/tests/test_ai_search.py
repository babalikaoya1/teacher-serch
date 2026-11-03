import asyncio

import httpx

from app.services import ai_search


def test_model_results_are_limited_to_known_order_ids(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, timeout):
            seen["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, headers, json):
            seen["url"] = url
            seen["headers"] = headers
            seen["body"] = json
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"matches":[{"id":7,"reason":"匹配"},{"id":999,"reason":"不存在"}]}'}}]},
                    request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(ai_search, "LLM_CHAT_COMPLETIONS_URL", "https://llm.invalid/custom/v1/")
    monkeypatch.setattr(ai_search, "LLM_API_KEY", "服务端测试密钥")
    monkeypatch.setattr(ai_search, "LLM_MODEL", "测试模型")
    monkeypatch.setattr(ai_search.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(ai_search.find_matching_jobs("找数学家教", [{"id": 7, "subject": "数学"}]))

    assert result == [{"id": 7, "reason": "匹配"}]
    assert seen["url"] == "https://llm.invalid/custom/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer 服务端测试密钥"
    assert seen["body"]["model"] == "测试模型"


def test_model_json_fences_and_text_blocks_are_supported():
    content = [{"type": "text", "text": '匹配结果如下：```json\n{"matches":[{"id":7,"reason":"符合"}]}\n```'}]
    assert ai_search.parse_matches_response(content) == [{"id": 7, "reason": "符合"}]
