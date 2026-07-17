import os
import time
import random
import requests
from datetime import datetime, timezone

from app.crawler.transcript import get_transcript
from app.crawler.description import get_description
from app.crawler.comment import get_top_comment
from app.crawler.channel import get_youtuber_name, get_existing_video_ids, get_channel_videos, is_daily_limit_exceeded
from app.llm.gemini import extract_recipe
from app.nutrition import register_new_ingredients, calculate_and_save_recipe_nutrition

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8080/api/v1/recipes")
SPRING_BASE_URL = os.environ.get(
    "SPRING_API_BASE_URL",
    API_BASE_URL.rsplit("/api/", 1)[0] if "/api/" in API_BASE_URL else "http://localhost:8080"
)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


def _is_blocked(e: Exception) -> bool:
    """IP 차단 / 봇 감지 예외 여부를 확인합니다."""
    name = type(e).__name__.lower()
    msg = str(e).lower()
    return (
        'blocked' in name or
        any(k in msg for k in ('blocked', '429', 'bot', 'captcha', 'sign in to confirm'))
    )


def _post_recipe(
    video_id: str,
    url: str,
    youtuber_name: str,
    title: str,
    ingredients: list,
    status: str,
    transcript: str,
) -> int | None:
    """레시피를 저장하고 생성된 레시피 id를 반환합니다. 실패 시 None."""
    payload = {
        "videoId": video_id,
        "title": title,
        "youtubeUrl": url,
        "status": status,
        "transcript": transcript,
        "ingredients": ingredients,
        "youtuberName": youtuber_name,
    }
    try:
        res = requests.post(API_BASE_URL, json=payload, timeout=15)
        if res.status_code not in (200, 201):
            print(f"  ❌ API 응답 오류: {res.status_code} - {res.text[:200]}")
            return None
        # Spring API가 id를 응답 본문에 포함하면 파싱, 아니면 None
        try:
            return res.json().get("id")
        except Exception:
            return None
    except requests.exceptions.ConnectionError:
        print("  ❌ API 서버 연결 실패")
    except Exception as e:
        print(f"  ❌ API 전송 오류: {e}")
    return None


def _fetch_master_name_map() -> dict[str, str]:
    """ingredient_mapping 전체를 조회해 raw_name → master_name 맵을 반환합니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/ingredients/mapped-names"
    try:
        res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
        if res.status_code == 200:
            return {item["rawName"]: item["masterName"] for item in res.json() if "rawName" in item}
    except Exception as e:
        print(f"  ⚠️ 매핑 테이블 조회 실패: {e}")
    return {}


def process_video(video_id: str, url: str, existing_ids: set, youtuber_name: str) -> str:
    print(f"\n▶ 영상 분석: {video_id}")

    if video_id in existing_ids:
        print("  ⏩ 스킵 (DB 존재)")
        return "SKIP"

    # 1. 자막 수집
    print("  ▶ 자막 수집")
    try:
        transcript = get_transcript(video_id) or ""
    except Exception as e:
        if _is_blocked(e):
            raise
        print(f"  ⚠️ 자막 수집 실패: {e} → description/댓글로 계속 진행")
        transcript = ""

    # 2. 더보기(description)
    print("  ▶ description 수집")
    try:
        description = get_description(video_id) or ""
    except Exception as e:
        if _is_blocked(e):
            raise
        print(f"  ⚠️ description 수집 실패: {e}")
        description = ""

    # 3. 댓글
    print("  ▶ 댓글 수집")
    try:
        comment = get_top_comment(video_id) or ""
    except Exception as e:
        if _is_blocked(e):
            raise
        print(f"  ⚠️ 댓글 수집 실패: {e}")
        comment = ""

    # 4. 세 소스 모두 비어있으면 NO_SUBTITLES
    if not transcript and not description and not comment:
        print("  ⚠️ 모든 소스 없음 → NO_SUBTITLES")
        _post_recipe(video_id, url, youtuber_name, "자막 없음", [], "NO_SUBTITLES", "")
        return "NO_SUBTITLES"

    # 5. Gemini 분석 (자막+더보기+댓글 전체를 한 번에 전달)
    print("  ▶ Gemini 분석")
    result = extract_recipe(transcript, description, comment)
    recipe_name = result.get("recipe_name", "레시피")
    ingredients = result.get("ingredients", [])

    if not ingredients:
        _post_recipe(video_id, url, youtuber_name, recipe_name or "자막 없음", [], "NO_SUBTITLES", transcript)
        return "NO_SUBTITLES"

    has_null_amount = any(i.get("amount") is None for i in ingredients)
    status = "INCOMPLETE" if has_null_amount else "SUCCESS"

    recipe_id = _post_recipe(video_id, url, youtuber_name, recipe_name, ingredients, status, transcript)
    print(f"  🎯 완료: [{recipe_name}] 재료 {len(ingredients)}개 → {status}")

    # 6. 영양성분 자동화 (recipe_id가 있을 때만)
    if recipe_id and status in ("SUCCESS", "INCOMPLETE"):
        try:
            master_map = _fetch_master_name_map()
            master_names = list({master_map.get(i["name"], i["name"]) for i in ingredients if i.get("name")})
            register_new_ingredients(master_names)
            calculate_and_save_recipe_nutrition(recipe_id, ingredients, master_map)
        except Exception as e:
            print(f"  ⚠️ 영양성분 자동화 실패 (레시피 저장은 성공): {e}")

    return status


def _update_recipe(recipe_id: int, title: str, ingredients: list, status: str, transcript: str) -> None:
    """어드민 API로 기존 레시피 상태·재료를 업데이트합니다."""
    url = f"{SPRING_BASE_URL}/api/v1/admin/recipes/{recipe_id}"
    payload = {"title": title, "status": status, "ingredients": ingredients, "transcript": transcript}
    try:
        res = requests.put(url, json=payload, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=15)
        if res.status_code not in (200, 201):
            print(f"  ❌ PUT 오류: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"  ❌ PUT 전송 오류: {e}")


def run_retry_no_subtitles(job_id: str, jobs: dict) -> None:
    """NO_SUBTITLES 상태 레시피를 재수집·재추출해서 상태를 업데이트합니다."""
    jobs[job_id]["status"] = "running"
    try:
        admin_url = f"{SPRING_BASE_URL}/api/v1/admin/recipes"
        res = requests.get(admin_url, params={"status": "NO_SUBTITLES"},
                           headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=15)
        if res.status_code != 200:
            raise Exception(f"어드민 API 조회 실패: {res.status_code} {res.text[:100]}")

        all_recipes = res.json()
        recipes = [r for r in all_recipes if r.get("status") == "NO_SUBTITLES"]
        print(f"📋 NO_SUBTITLES 레시피 {len(recipes)}건 재처리 시작")
        jobs[job_id]["total"] = len(recipes)

        for recipe in recipes:
            recipe_id = recipe.get("id")
            video_id = recipe.get("videoId")
            if not video_id:
                continue

            print(f"\n▶ 재처리: {video_id} (id={recipe_id})")

            try:
                transcript = get_transcript(video_id) or ""
            except Exception as e:
                if _is_blocked(e): raise
                transcript = ""

            try:
                description = get_description(video_id) or ""
            except Exception as e:
                if _is_blocked(e): raise
                description = ""

            try:
                comment = get_top_comment(video_id) or ""
            except Exception as e:
                if _is_blocked(e): raise
                comment = ""

            if not transcript and not description and not comment:
                print("  ⚠️ 모든 소스 없음 → 스킵")
                jobs[job_id]["processed"] += 1
                jobs[job_id]["results"]["NO_SUBTITLES"] = jobs[job_id]["results"].get("NO_SUBTITLES", 0) + 1
                time.sleep(random.uniform(30, 60))
                continue

            result = extract_recipe(transcript, description, comment)
            recipe_name = result.get("recipe_name", "레시피")
            ingredients = result.get("ingredients", [])

            if not ingredients:
                print("  ⚠️ 재료 없음 → NO_SUBTITLES 유지")
                jobs[job_id]["processed"] += 1
                jobs[job_id]["results"]["NO_SUBTITLES"] = jobs[job_id]["results"].get("NO_SUBTITLES", 0) + 1
                time.sleep(random.uniform(30, 60))
                continue

            status = "INCOMPLETE" if any(i.get("amount") is None for i in ingredients) else "SUCCESS"
            _update_recipe(recipe_id, recipe_name, ingredients, status, transcript)
            print(f"  🎯 업데이트: [{recipe_name}] 재료 {len(ingredients)}개 → {status}")

            # 영양성분 자동화
            try:
                master_map = _fetch_master_name_map()
                master_names = list({master_map.get(i["name"], i["name"]) for i in ingredients if i.get("name")})
                register_new_ingredients(master_names)
                calculate_and_save_recipe_nutrition(recipe_id, ingredients, master_map)
            except Exception as e:
                print(f"  ⚠️ 영양성분 자동화 실패: {e}")

            jobs[job_id]["processed"] += 1
            jobs[job_id]["results"][status] = jobs[job_id]["results"].get(status, 0) + 1

            sleep_time = random.uniform(30, 60)
            print(f"  ⏳ {sleep_time:.1f}초 대기")
            time.sleep(sleep_time)

        jobs[job_id]["status"] = "done"
        print(f"\n✅ 재처리 완료: {jobs[job_id]['results']}")

    except Exception as e:
        if _is_blocked(e):
            jobs[job_id]["status"] = "blocked"
            jobs[job_id]["error"] = "IP 차단 감지"
            print(f"⛔ IP 차단: {e}")
        else:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(e)
            print(f"❌ 재처리 실패: {e}")
    finally:
        jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def run_single_video(video_url: str, youtuber_name: str, job_id: str, jobs: dict) -> None:
    jobs[job_id]["status"] = "running"
    try:
        video_id = video_url.split("v=")[-1].split("&")[0] if "v=" in video_url else video_url.rstrip("/").split("/")[-1]
        existing_ids = get_existing_video_ids(API_BASE_URL)
        status = process_video(video_id, video_url, existing_ids, youtuber_name)
        jobs[job_id]["processed"] = 1
        results = jobs[job_id]["results"]
        results[status] = results.get(status, 0) + 1
        jobs[job_id]["status"] = "done"
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
    finally:
        jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def run_channel_crawl(channel_url: str, start: int, end: int, job_id: str, jobs: dict) -> None:
    jobs[job_id]["status"] = "running"

    try:
        print(f"\n🔍 채널 크롤링 시작: {channel_url} ({start}~{end})")
        youtuber_name = get_youtuber_name(channel_url)
        print(f"🧑‍🍳 유튜버: {youtuber_name}")

        existing_ids = get_existing_video_ids(API_BASE_URL)
        videos, total_videos = get_channel_videos(channel_url, start, end)
        jobs[job_id]["total"] = len(videos)
        jobs[job_id]["total_videos"] = total_videos
        print(f"📊 채널 전체 숏츠: {total_videos}개 / 이번 범위: {len(videos)}개")

        for video in videos:
            if is_daily_limit_exceeded(jobs):
                jobs[job_id]["error"] = "Gemini 일일 한도(1400건) 초과로 중단"
                break

            video_id = video.get("videoId")
            if not video_id:
                continue

            url = f"https://www.youtube.com/watch?v={video_id}"
            status = process_video(video_id, url, existing_ids, youtuber_name)

            jobs[job_id]["processed"] += 1
            results = jobs[job_id]["results"]
            results[status] = results.get(status, 0) + 1

            if status == "SKIP":
                continue

            sleep_time = random.uniform(30, 60)
            print(f"  ⏳ {sleep_time:.1f}초 대기")
            time.sleep(sleep_time)

        jobs[job_id]["status"] = "done"
        print(f"\n✅ 크롤링 완료: {jobs[job_id]['results']}")

    except Exception as e:
        if _is_blocked(e):
            jobs[job_id]["status"] = "blocked"
            jobs[job_id]["error"] = "IP 차단 감지, 크롤링 중단"
            print(f"⛔ IP 차단 감지, 크롤링 중단: {e}")
        else:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(e)
            print(f"❌ 크롤링 실패: {e}")

    finally:
        jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
