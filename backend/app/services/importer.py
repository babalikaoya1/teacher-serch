import re

SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "编程", "钢琴")
JOB_HINTS = ("家教", "辅导", "陪读", "找老师", "招老师", "招聘", "上门", "学生")
SALARY_RE = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>元[/／]?(?:小时|时|次|天)?|块[/／]?(?:小时|时|次)?|k|K)")


def parse_message(line: str) -> dict | None:
    text = line.strip()
    if not text or not any(hint in text for hint in JOB_HINTS):
        return None
    subject = next((value for value in SUBJECTS if value in text), None)
    salary_match = SALARY_RE.search(text)
    salary = float(salary_match.group("amount")) if salary_match else None
    salary_unit = salary_match.group("unit") if salary_match else None
    grade_match = re.search(r"(小学|初中|高中|高一|高二|高三|[一二三四五六]年级)", text)
    schedule_match = re.search(r"(周[一二三四五六日末天].{0,12}|每周.{0,12}|周末.{0,12})", text)
    location_match = re.search(r"(?:地点|地址)?在?([一-龥]{2,12}(?:区|县|镇|街道|地铁站))", text)
    return {
        "subject": subject,
        "grade": grade_match.group(1) if grade_match else None,
        "location": location_match.group(1) if location_match else None,
        "salary": salary,
        "salary_unit": salary_unit,
        "schedule": schedule_match.group(1).strip() if schedule_match else None,
        "raw_text": text,
    }


def preview_messages(content: str) -> tuple[list[dict], int]:
    jobs = []
    ignored = 0
    for line in content.splitlines():
        item = parse_message(line)
        if item:
            jobs.append(item)
        elif line.strip():
            ignored += 1
    return jobs, ignored
