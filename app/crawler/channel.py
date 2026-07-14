import urllib.parse
import requests
import scrapetube
from datetime import date

# Gemini Flash 일일 RPD 한도(1500)에서 여유치 100 확보
GEMINI_DAILY_LIMIT = 1400


def get_youtuber_name(channel_url: str) -> str:
    if "@" in channel_url:
        extracted = channel_url.split("@")[-1]
        return urllib.parse.unquote(extracted).replace("/", "")
    return "알 수 없음"


def get_existing_video_ids(api_base_url: str) -> set:
    """API에서 기존 레시피 videoId 목록을 가져와 중복 적재를 방지한다."""
    try:
        res = requests.get(api_base_url, timeout=10)
        if res.status_code == 200:
            ids = {r["videoId"] for r in res.json() if r.get("videoId")}
            print(f"📡 기존 레시피 {len(ids)}개 확인 완료")
            return ids
    except Exception:
        print("⚠️ 기존 레시피 조회 실패 (모두 새로 처리)")
    return set()


def get_channel_videos(channel_url: str, start: int, end: int) -> tuple[list, int]:
    """채널의 숏츠 영상을 가져옵니다.

    Returns:
        (요청 범위 슬라이스, 채널 전체 숏츠 수) 튜플.
        전체 수는 scrapetube가 이미 모두 fetch하므로 추가 API 호출 없음.
    """
    try:
        generator = scrapetube.get_channel(channel_url=channel_url, content_type="shorts")
        videos = list(generator)
        total = len(videos)
        idx = max(start - 1, 0)
        return videos[idx:end], total
    except Exception as e:
        print(f"❌ 채널 영상 목록 조회 실패: {e}")
        return [], 0


def count_today_gemini_calls(jobs: dict) -> int:
    """오늘 날짜 기준 Gemini API 실제 호출 건수를 in-memory jobs에서 집계합니다.

    SKIP은 Gemini를 호출하지 않으므로 processed - SKIP 으로 계산합니다.
    """
    today = date.today().isoformat()  # "YYYY-MM-DD"
    total = 0
    for job in jobs.values():
        started = job.get("started_at", "")
        if started and started[:10] == today:
            results = job.get("results", {})
            skip_count = results.get("SKIP", 0)
            total += max(job.get("processed", 0) - skip_count, 0)
    return total


def is_daily_limit_exceeded(jobs: dict) -> bool:
    """오늘 Gemini 호출 건수가 GEMINI_DAILY_LIMIT(1400)을 초과하면 True를 반환합니다."""
    count = count_today_gemini_calls(jobs)
    if count >= GEMINI_DAILY_LIMIT:
        print(f"⛔ Gemini 일일 한도 초과: 오늘 {count}건 처리 (한도: {GEMINI_DAILY_LIMIT})")
        return True
    return False
