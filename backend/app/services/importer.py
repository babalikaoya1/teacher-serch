import re


SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "编程", "钢琴", "作业辅导")
JOB_HINTS = ("家教", "辅导", "陪读", "找老师", "招老师", "招聘", "上门", "学生", "【编号】", "【科目】")
HEADER_RE = re.compile(r"^[\s🌸⭐✨【】#]*[一-龥]{2,10}(?:区|县|市)\s*(?:线上|线下)?\s*家教")
CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{5,})\b")
STRUCTURED_LINE_RE = re.compile(r"^\s*(?:【\s*(?:编号|订单编号|联系地址|地址|地点|年级性别|年级|辅导科目|科目|学员情况|学生情况|时间安排|课次|上课时间|教员要求|要求|薪资待遇|时薪|周薪)\s*】|(?:联系地址|地址|地点|年级性别|年级|辅导科目|科目|学员情况|学生情况|时间安排|课次|上课时间|教员要求|要求|薪资待遇|时薪|周薪)\s*[:：])")
HOURLY_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<minimum>\+)?\s*(?P<unit>元\s*[/／]\s*(?:小时|时)|块\s*[/／]\s*(?:小时|时)|[/／]\s*h)",
    re.IGNORECASE,
)
WEEKLY_RE = re.compile(r"周薪\s*[#￥¥:]?\s*(?P<amount>\d+(?:\.\d+)?)")
SESSION_RE = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*元\s*[/／]\s*次")


def _split_blocks(content: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []

    def finish() -> None:
        nonlocal current
        if current:
            blocks.append(current)
            current = []

    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            finish()
            continue
        if current and (HEADER_RE.match(stripped) or re.match(r"^【\s*编号\s*】", stripped)):
            finish()
        elif current and (HOURLY_RE.search("\n".join(current)) or WEEKLY_RE.search("\n".join(current))) and not STRUCTURED_LINE_RE.match(stripped) and not stripped.startswith(("🌸", "⭐", "✨")) and not CODE_RE.search(stripped):
            finish()
        current.append(stripped)
    finish()
    return blocks


def _label_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"^\s*【?\s*(?:{label_pattern})\s*】?\s*[:：]\s*(.*)$")
    for line in lines:
        match = pattern.match(line)
        if match:
            value = match.group(1).strip().lstrip("#＃ ").strip()
            return value or None
    return None


def _parse_salary(text: str) -> tuple[float | None, str | None, str | None, bool]:
    hourly = list(HOURLY_RE.finditer(text))
    if hourly:
        match = hourly[-1]
        unit = match.group("unit").lower().replace("／", "/")
        if unit.endswith("/h"):
            normalized_unit = "元/小时"
        else:
            normalized_unit = re.sub(r"\s+", "", unit)
        return float(match.group("amount")), normalized_unit, "hour", bool(match.group("minimum"))

    weekly = WEEKLY_RE.search(text)
    if weekly:
        return float(weekly.group("amount")), "周薪", "week", False

    session = SESSION_RE.search(text)
    if session:
        return float(session.group("amount")), "元/次", "session", False

    return None, None, None, False


def parse_message(block: str, source_group: str | None = None) -> dict | None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    text = "\n".join(lines)
    if not lines or not any(hint in text for hint in JOB_HINTS):
        return None

    headline = lines[0]
    mode = "线上" if "线上" in text else "线下" if "线下" in text else None
    location = _label_value(lines, ("联系地址", "地址", "地点"))
    if location is None:
        inline_location = re.search(r"(?:联系地址|地址|地点)(?:在)?\s*[#＃]?([一-龥0-9·.()（）\-]{2,30}?(?:区|县|镇|街道|地铁站))", text)
        location = inline_location.group(1).strip() if inline_location else None
    if location is None:
        region_match = re.search(r"([一-龥]{2,10}(?:区|县|市))\s*(?:线上|线下)?\s*家教", headline)
        location = region_match.group(1) if region_match else None
    if location and location in ("线上", "网课"):
        mode = "线上"

    subject = _label_value(lines, ("辅导科目", "科目"))
    if subject is None:
        found_subjects = [value for value in SUBJECTS if value in text]
        subject = " ".join(found_subjects) or None

    grade_value = _label_value(lines, ("年级性别", "年级"))
    grade = None
    gender = None
    grade_source = grade_value or text
    grade_match = re.search(r"(小学?[一二三四五六1-6]年级|[一二三四五六1-6]年级|初[一二三]|高[一二三]|小学|初中|高中)", grade_source)
    if grade_value:
        grade = grade_match.group(1) if grade_match else grade_value.split("，")[0].split(",")[0].strip()
    elif grade_match:
        grade = grade_match.group(1)
    if grade_value:
        gender_match = re.search(r"(男|女)(?:生)?(?:\s|$|[,，])", grade_value)
        gender = gender_match.group(1) if gender_match else None

    schedule = _label_value(lines, ("时间安排", "课次", "上课时间"))
    if schedule is None:
        schedule_match = re.search(r"((?:每周|周末|周[一二三四五六日天])[^\n，,。；;]{0,40})", text)
        schedule = schedule_match.group(1).strip() if schedule_match else None

    salary, salary_unit, salary_basis, salary_is_minimum = _parse_salary(text)
    order_code = _label_value(lines, ("编号", "订单编号"))
    if order_code is None:
        code_match = CODE_RE.search(text)
        order_code = code_match.group(1) if code_match else None

    student_notes = _label_value(lines, ("学员情况", "学生情况"))
    requirements = _label_value(lines, ("教员要求", "要求"))
    return {
        "subject": subject,
        "grade": grade,
        "gender": gender,
        "location": location,
        "teaching_mode": mode,
        "salary": salary,
        "salary_unit": salary_unit,
        "salary_basis": salary_basis,
        "salary_is_minimum": salary_is_minimum,
        "schedule": schedule,
        "order_code": order_code,
        "student_notes": student_notes,
        "requirements": requirements,
        "source_group": source_group,
        "raw_text": text,
    }


def preview_messages(content: str, source_group: str | None = None) -> tuple[list[dict], int]:
    jobs: list[dict] = []
    ignored_lines = 0
    for lines in _split_blocks(content):
        item = parse_message("\n".join(lines), source_group)
        if item:
            jobs.append(item)
        else:
            ignored_lines += len(lines)
    return jobs, ignored_lines
