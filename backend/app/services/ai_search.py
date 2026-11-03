import json
import re

import httpx

from ..ai_config import LLM_API_KEY, LLM_CHAT_COMPLETIONS_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS


class AIConfigurationError(Exception):
    pass


class AIProviderError(Exception):
    pass


def normalize_chat_completions_url(configured_url: str) -> str:
    url = configured_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def parse_matches_response(content: object) -> list:
    if isinstance(content, list):
        content = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    if not isinstance(content, str):
        raise TypeError("模型回复 content 格式不正确")

    content = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()
    if not content.startswith("{"):
        first_object = content.find("{")
        last_object = content.rfind("}")
        if first_object < 0 or last_object <= first_object:
            raise ValueError("模型回复中没有 JSON 对象")
        content = content[first_object:last_object + 1]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise TypeError("模型回复 JSON 顶层不是对象")
    matches = parsed.get("matches", [])
    if not isinstance(matches, list):
        raise ValueError("matches 字段不是列表")
    return matches


async def find_matching_jobs(query: str, jobs: list[dict]) -> list[dict]:
    if not (LLM_CHAT_COMPLETIONS_URL and LLM_API_KEY and LLM_MODEL):
        raise AIConfigurationError("大模型尚未配置，请在 backend/.env 中填写接口地址、密钥和模型名。")
    if not jobs:
        return []

    job_list = [
        {
            "id": job["id"],
            "科目": job.get("subject"),
            "年级": job.get("grade"),
            "地点": job.get("location"),
            "授课方式": job.get("teaching_mode"),
            "薪资": job.get("salary"),
            "薪资口径": job.get("salary_basis"),
            "时间": job.get("schedule"),
            "要求": job.get("requirements"),
            "原始订单": job.get("raw_text"),
        }
        for job in jobs
    ]
    request_body = {
        "model": LLM_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是家教订单筛选助手。只根据用户需求匹配给出的订单，不要编造订单或字段。"
                    "输出严格 JSON 对象，格式为 {\"matches\":[{\"id\":订单整数ID,\"reason\":\"简短中文匹配原因\"}]}。"
                    "只返回符合需求的订单，按匹配程度排序；没有合适订单时返回空数组。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"需求": query, "可选订单": job_list}, ensure_ascii=False),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                normalize_chat_completions_url(LLM_CHAT_COMPLETIONS_URL),
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json=request_body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        matches = parse_matches_response(content)
        allowed_ids = {job["id"] for job in jobs}
        result = []
        seen = set()
        for item in matches:
            if not isinstance(item, dict):
                continue
            job_id = item.get("id")
            if isinstance(job_id, int) and job_id in allowed_ids and job_id not in seen:
                seen.add(job_id)
                result.append({"id": job_id, "reason": str(item.get("reason", "符合所描述的筛选条件"))[:240]})
        return result
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            detail = f"大模型服务商拒绝鉴权（HTTP {status}），请检查 API Key 是否有效、是否有模型调用权限。"
        elif status == 404:
            detail = "大模型接口返回 HTTP 404，请核对服务商域名、地域和兼容接口路径。"
        elif status == 400:
            detail = "大模型接口返回 HTTP 400，请核对模型名称和请求参数是否受服务商支持。"
        else:
            detail = f"大模型接口返回 HTTP {status}，请检查服务商状态和接口配置。"
        raise AIProviderError(detail) from exc
    except httpx.TimeoutException as exc:
        raise AIProviderError("大模型请求超时，请检查服务商响应状态或适当延长 LLM_TIMEOUT_SECONDS。") from exc
    except httpx.RequestError as exc:
        raise AIProviderError("无法连接大模型服务，请核对接口域名、网络和 TLS 配置。") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIProviderError("大模型查询失败，请检查接口地址、模型配置及服务商返回格式。") from exc
