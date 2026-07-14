import os
import time
import random
import requests
from datetime import datetime

from app.crawler.transcript import get_transcript
from app.crawler.description import get_description
from app.crawler.comment import get_top_comment
from app.crawler.channel import get_youtuber_name, get_existing_video_ids, get_channel_videos
from app.llm.gemini import extract_recipe

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8080/api/v1/recipes")


def _post_recipe(
    video_id: str,
    url: str,
    youtuber_name: str,
    title: str,
    ingredients: list,
    status: str,
    transcript: str,
) -> None:
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
    except requests.exceptions.ConnectionError:
        print("  ❌ API 서버 연결 실패")
    except Exception as e:
        print(f"  ❌ API 전송 오류: {e}")


def process_video(video_id: str, url: str, existing_ids: set, youtuber_name: str) -> str:
    print(f"\n▶ 영상 분석: {video_id}")

    if video_id in existing_ids:
        print("  ⏩ 스킵 (DB 존재)")
        return "SKIP"

    # 1. 자막 수집
    print("  ▶ 자막 수집")
    transcript = get_transcript(video_id)

    if not transcript:
        print("  ⚠️ 자막 없음 → NO_SUBTITLES")
        _post_recipe(video_id, url, youtuber_name, "자막 없음", [], "NO_SUBTITLES", "")
        return "NO_SUBTITLES"

    # 2. 더보기(description) + 댓글 수집 — 실패해도 계속 진행
    print("  ▶ description 수집")
    description = get_description(video_id)

    print("  ▶ 댓글 수집")
    comment = get_top_comment(video_id)

    # 3. Gemini 분석
    print("  ▶ Gemini 분석")
    result = extract_recipe(transcript, description, comment)
    recipe_name = result.get("recipe_name", "레시피")
    ingredients = result.get("ingredients", [])

    if not ingredients:
        status = "AI_ERROR"
    elif any(i.get("amount") is None for i in ingredients):
        status = "NEEDS_REVIEW"
    else:
        status = "SUCCESS"

    _post_recipe(video_id, url, youtuber_name, recipe_name, ingredients, status, transcript)
    print(f"  🎯 완료: [{recipe_name}] 재료 {len(ingredients)}개 → {status}")
    return status


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
        jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()


def run_channel_crawl(channel_url: str, start: int, end: int, job_id: str, jobs: dict) -> None:
    jobs[job_id]["status"] = "running"

    try:
        print(f"\n🔍 채널 크롤링 시작: {channel_url} ({start}~{end})")
        youtuber_name = get_youtuber_name(channel_url)
        print(f"🧑‍🍳 유튜버: {youtuber_name}")

        existing_ids = get_existing_video_ids(API_BASE_URL)
        videos = get_channel_videos(channel_url, start, end)
        jobs[job_id]["total"] = len(videos)

        for video in videos:
            video_id = video.get("videoId")
            if not video_id:
                continue

            url = f"https://www.youtube.com/watch?v={video_id}"
            status = process_video(video_id, url, existing_ids, youtuber_name)

            jobs[job_id]["processed"] += 1
            results = jobs[job_id]["results"]
            results[status] = results.get(status, 0) + 1

            # 스킵 영상은 대기 없이 즉시 다음으로
            if status == "SKIP":
                continue

            sleep_time = random.uniform(20, 40)
            print(f"  ⏳ {sleep_time:.1f}초 대기")
            time.sleep(sleep_time)

        jobs[job_id]["status"] = "done"
        print(f"\n✅ 크롤링 완료: {jobs[job_id]['results']}")

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        print(f"❌ 크롤링 실패: {e}")

    finally:
        jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()
