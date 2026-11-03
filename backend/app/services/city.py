import re


def normalize_city_name(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    city = re.sub(r"\s+", "", value.strip())
    city = re.sub(r"(市|地区|自治州|盟)$", "", city)
    return city or None
