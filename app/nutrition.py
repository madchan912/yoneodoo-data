"""
레시피 영양성분 자동화 모듈.

흐름:
1. 새 재료 발견 시 Gemini로 영양성분 추정 → PUT /api/v1/admin/nutrition/{masterName}
2. recipe_nutrition 계산 → POST /api/v1/recipes/{id}/nutrition
"""

import os
import requests
from decimal import Decimal, InvalidOperation

from app.llm.gemini import extract_nutrition

SPRING_BASE_URL = os.environ.get(
    "SPRING_API_BASE_URL",
    os.environ.get("API_BASE_URL", "http://localhost:8080/api/v1/recipes")
    .rsplit("/api/", 1)[0] if "/api/" in os.environ.get("API_BASE_URL", "")
    else "http://localhost:8080"
)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# 단위 → g 변환 (근사값)
UNIT_TO_GRAM: dict[str, float] = {
    "g": 1, "kg": 1000, "ml": 1, "l": 1000,
    "큰술": 15, "tbsp": 15, "T": 15,
    "작은술": 5, "tsp": 5, "t": 5,
    "컵": 200, "cup": 200,
    "꼬집": 1,
}

# 개수 단위 → g (재료별 평균 무게)
ITEM_WEIGHT: dict[str, float] = {
    "달걀": 60, "계란": 60,
    "감자": 150, "고구마": 150,
    "양파": 200, "당근": 150,
    "두부": 300, "애호박": 250, "오이": 200,
}


def _parse_amount(amount_str: str, ingredient_name: str) -> float | None:
    """amount 문자열을 g 단위 숫자로 변환합니다. 변환 불가면 None 반환."""
    if not amount_str:
        return None
    s = amount_str.strip()

    # 숫자 추출
    num_str = ""
    for ch in s:
        if ch.isdigit() or ch == "." or ch == "/":
            num_str += ch
        else:
            break

    if not num_str:
        return None

    try:
        if "/" in num_str:
            parts = num_str.split("/")
            num = float(parts[0]) / float(parts[1])
        else:
            num = float(num_str)
    except (ValueError, ZeroDivisionError):
        return None

    unit_part = s[len(num_str):].strip()

    # 개수 단위 처리 (개, 장, 쪽 등)
    if unit_part in ("개", "장", "쪽", "알", "조각", "뭉치", "줄기") or not unit_part:
        weight = ITEM_WEIGHT.get(ingredient_name)
        if weight:
            return num * weight
        return None  # 무게 모름

    for unit, gram in UNIT_TO_GRAM.items():
        if unit_part.startswith(unit):
            return num * gram

    return None


def _fetch_known_master_names() -> set[str]:
    """ingredient_nutrition에 이미 등록된 master_name 목록을 가져옵니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/nutrition/matched"
    try:
        res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
        if res.status_code == 200:
            return {item.get("masterName", "") for item in res.json()}
    except Exception as e:
        print(f"  ⚠️ 영양성분 목록 조회 실패: {e}")
    return set()


def _fetch_manual_needed_names() -> set[str]:
    """source=manual_needed인 재료 이름 집합을 가져옵니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/nutrition/manual-needed"
    try:
        res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
        if res.status_code == 200:
            return {item.get("masterName", "") for item in res.json()}
    except Exception as e:
        print(f"  ⚠️ manual-needed 목록 조회 실패: {e}")
    return set()


def _upsert_ingredient_nutrition(master_name: str, nutrition: dict, source: str) -> None:
    """PUT /api/v1/admin/nutrition/{masterName} 으로 영양성분을 저장합니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/nutrition/{requests.utils.quote(master_name, safe='')}"
    payload = {
        "calories": nutrition.get("calories"),
        "protein": nutrition.get("protein"),
        "fat": nutrition.get("fat"),
        "saturatedFat": nutrition.get("saturated_fat"),
        "carbohydrate": nutrition.get("carbohydrate"),
        "sugar": nutrition.get("sugar"),
        "sodium": nutrition.get("sodium"),
        "source": source,
    }
    try:
        res = requests.put(url, json=payload, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=15)
        if res.status_code not in (200, 201):
            print(f"  ❌ 영양성분 저장 오류: {res.status_code} - {res.text[:100]}")
    except Exception as e:
        print(f"  ❌ 영양성분 저장 전송 오류: {e}")


def register_new_ingredients(master_names: list[str]) -> None:
    """
    ingredient_nutrition에 없는 재료를 Gemini로 추정해 등록합니다.
    이미 등록된 재료(matched + manual_needed)는 건너뜁니다.
    """
    known = _fetch_known_master_names() | _fetch_manual_needed_names()
    new_names = [n for n in master_names if n and n not in known]
    if not new_names:
        return

    print(f"  📊 새 재료 {len(new_names)}개 영양성분 등록 시작")
    for name in new_names:
        print(f"    → {name} 추정 중...")
        nutrition = extract_nutrition(name)
        has_values = any(v is not None for v in nutrition.values())
        source = "gemini_est" if has_values else "manual_needed"
        _upsert_ingredient_nutrition(name, nutrition if has_values else {}, source)
        print(f"    ✅ {name}: {source}")


def _fetch_ingredient_nutrition(master_names: list[str]) -> dict[str, dict]:
    """ingredient_nutrition 전체를 조회해 master_name → 영양 dict 맵을 반환합니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/nutrition/matched"
    try:
        res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
        if res.status_code != 200:
            return {}
        all_items = {item["masterName"]: item for item in res.json()}
        return {n: all_items[n] for n in master_names if n in all_items}
    except Exception as e:
        print(f"  ⚠️ 영양성분 조회 실패: {e}")
    return {}


def calculate_and_save_recipe_nutrition(recipe_id: int, ingredients: list[dict], master_name_map: dict[str, str]) -> None:
    """
    재료 목록을 바탕으로 레시피 영양 합계를 계산하고
    POST /api/v1/recipes/{id}/nutrition 으로 저장합니다.

    master_name_map: raw_name → master_name 매핑 (ingredient_mapping 기준)
    """
    master_names = list({master_name_map.get(i["name"], i["name"]) for i in ingredients if i.get("name")})
    nutrition_map = _fetch_ingredient_nutrition(master_names)

    keys = ["calories", "protein", "fat", "saturatedFat", "carbohydrate", "sugar", "sodium"]
    totals = {k: Decimal("0") for k in keys}
    covered = 0

    for ing in ingredients:
        raw_name = ing.get("name", "")
        master = master_name_map.get(raw_name, raw_name)
        amount_str = ing.get("amount") or ""
        gram = _parse_amount(amount_str, master)

        if gram is None or master not in nutrition_map:
            continue

        n = nutrition_map[master]
        ratio = Decimal(str(gram)) / Decimal("100")
        field_map = {
            "calories": "calories", "protein": "protein", "fat": "fat",
            "saturatedFat": "saturatedFat", "carbohydrate": "carbohydrate",
            "sugar": "sugar", "sodium": "sodium",
        }
        for k, api_key in field_map.items():
            val = n.get(api_key)
            if val is not None:
                try:
                    totals[k] += Decimal(str(val)) * ratio
                except InvalidOperation:
                    pass
        covered += 1

    total_count = len(ingredients)
    coverage_pct = round(covered / total_count * 100, 2) if total_count > 0 else 0.0

    payload = {
        "calories": float(round(totals["calories"], 2)),
        "protein": float(round(totals["protein"], 2)),
        "fat": float(round(totals["fat"], 2)),
        "saturatedFat": float(round(totals["saturatedFat"], 2)),
        "carbohydrate": float(round(totals["carbohydrate"], 2)),
        "sugar": float(round(totals["sugar"], 2)),
        "sodium": float(round(totals["sodium"], 2)),
        "coveragePct": coverage_pct,
    }

    url = f"{SPRING_BASE_URL}/api/v1/recipes/{recipe_id}/nutrition"
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code not in (200, 201):
            print(f"  ❌ recipe_nutrition 저장 오류: {res.status_code}")
        else:
            print(f"  📊 영양성분 저장: {payload['calories']:.0f}kcal (coverage {coverage_pct:.0f}%)")
    except Exception as e:
        print(f"  ❌ recipe_nutrition 전송 오류: {e}")
