import json
import re
from typing import Any

import httpx

from ..ai_config import LLM_API_KEY, LLM_CHAT_COMPLETIONS_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS


class AIConfigurationError(Exception):
    pass


class AIProviderError(Exception):
    pass


MAX_AI_CANDIDATES = 30

_SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "科学", "编程", "钢琴", "美术")
_GRADE_GROUPS = {
    "小学": ("小学", "一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "1年级", "2年级", "3年级", "4年级", "5年级", "6年级"),
    "初中": ("初中", "初一", "初二", "初三", "七年级", "八年级", "九年级"),
    "高中": ("高中", "高一", "高二", "高三"),
}
_PREFERENCE_TERMS = ("有经验", "经验丰富", "耐心", "细心", "责任心", "专职", "清北", "男女不限")
_STOP_TERMS = ("附近", "周边", "想找", "帮我找", "找一份", "找个", "家教", "老师", "订单", "优先", "最好", "希望", "需要", "要求", "上课", "授课", "一份", "一个")


def _query_criteria(query: str) -> dict[str, Any]:
    subjects = [subject for subject in _SUBJECTS if subject in query]
    grade_groups = [name for name, terms in _GRADE_GROUPS.items() if any(term in query for term in terms)]
    locations = [match.group(1) for match in re.finditer(r"([\u4e00-\u9fff]{2,8})(?:附近|周边)", query)]
    locations.extend(match.group(1) for match in re.finditer(r"([\u4e00-\u9fff]{2,8}(?:区|县|市))", query))
    locations = list(dict.fromkeys(locations))

    salary_match = re.search(
        r"(?:時薪|时薪|每小时|小时|元\s*/\s*(?:小时|h))?\s*(\d+(?:\.\d+)?)\s*(?:元\s*)?(?:以上|起|及以上|不低于|至少|\+|>=)",
        query,
        flags=re.IGNORECASE,
    )
    salary_basis = None
    if any(term in query.lower() for term in ("时薪", "每小时", "/小时", "/h", "小时")):
        salary_basis = "hour"
    elif any(term in query for term in ("周薪", "每周")):
        salary_basis = "week"
    elif "按次" in query:
        salary_basis = "session"

    return {
        "subjects": subjects,
        "grades": grade_groups,
        "locations": locations,
        "minimum_salary": float(salary_match.group(1)) if salary_match else None,
        "salary_basis": salary_basis,
        "weekend": any(term in query for term in ("周末", "周六", "周日", "星期六", "星期日", "星期天")),
    }


def _candidate_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(field) or "")
        for field in ("subject", "grade", "city", "location", "teaching_mode", "salary_basis", "salary_unit", "schedule", "requirements", "student_notes")
    ).lower()


def _normalize_place(value: str) -> str:
    return re.sub(r"市|区|县|地区|自治州|盟|旗", "", value).lower()


def select_candidate_jobs(query: str, jobs: list[dict], limit: int = MAX_AI_CANDIDATES) -> list[dict]:
    """先按可识别的明确条件筛选，再按可读字段相关度排序。"""
    criteria = _query_criteria(query)
    ranked: list[tuple[int, int, dict]] = []
    strict_candidates: list[tuple[int, int, dict]] = []

    for index, job in enumerate(jobs):
        text = _candidate_text(job)
        subject = str(job.get("subject") or "").lower()
        grade = str(job.get("grade") or "").lower()
        place = _normalize_place(f"{job.get('city') or ''} {job.get('location') or ''}")
        schedule = str(job.get("schedule") or "").lower()
        score = 0
        strict_match = True

        for term in criteria["subjects"]:
            if subject and term not in subject:
                strict_match = False
            if term in text:
                score += 5
        for group in criteria["grades"]:
            terms = _GRADE_GROUPS[group]
            if grade and not any(term.lower() in grade for term in terms):
                score -= 4
            elif grade:
                score += 3
        for location in criteria["locations"]:
            normalized_location = _normalize_place(location)
            if place and normalized_location not in place:
                strict_match = False
            if normalized_location in place:
                score += 5
        if criteria["minimum_salary"] is not None and job.get("salary") is not None:
            requested_basis = criteria["salary_basis"]
            actual_basis = job.get("salary_basis")
            if requested_basis and actual_basis and requested_basis != actual_basis:
                strict_match = False
            elif float(job["salary"]) < criteria["minimum_salary"]:
                strict_match = False
            else:
                score += 4
        if criteria["weekend"]:
            if any(term in schedule for term in ("周末", "周六", "周日", "星期六", "星期日", "星期天")):
                score += 3
            elif schedule:
                score -= 2
        for term in _PREFERENCE_TERMS:
            if term in query and term in text:
                score += 2

        for token in re.findall(r"[a-zA-Z]{2,}|\d{2,}", query.lower()):
            if token in text:
                score += 1
        ranked.append((score, index, job))
        if strict_match:
            strict_candidates.append((score, index, job))

    # 明确条件有结果时遵从条件；完全无命中时放宽筛选，交由模型判断不完整或模糊字段。
    pool = strict_candidates or ranked
    pool.sort(key=lambda item: (-item[0], -int(item[2].get("id") or 0), item[1]))
    return [item[2] for item in pool[:max(1, limit)]]


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
            "科目": str(job.get("subject") or "")[:120],
            "年级": str(job.get("grade") or "")[:80],
            "城市": str(job.get("city") or "")[:80],
            "地点": str(job.get("location") or "")[:120],
            "授课方式": str(job.get("teaching_mode") or "")[:40],
            "薪资": job.get("salary"),
            "薪资口径": str(job.get("salary_basis") or "")[:40],
            "时间": str(job.get("schedule") or "")[:240],
            "学生情况": str(job.get("student_notes") or "")[:240],
            "教员要求": str(job.get("requirements") or "")[:240],
        }
        for job in jobs[:MAX_AI_CANDIDATES]
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
    except httpx.ConnectError as exc:
        raise AIProviderError("无法连接大模型服务，请核对接口地址、网络连通性及 TLS 配置。") from exc
    except httpx.RequestError as exc:
        raise AIProviderError("无法连接大模型服务，请核对接口域名、网络和 TLS 配置。") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIProviderError("大模型查询失败，请检查接口地址、模型配置及服务商返回格式。") from exc
