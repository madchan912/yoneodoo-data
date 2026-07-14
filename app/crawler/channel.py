import urllib.parse
import requests
import scrapetube


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


def get_channel_videos(channel_url: str, start: int, end: int) -> list:
    try:
        generator = scrapetube.get_channel(channel_url=channel_url, content_type="shorts")
        videos = list(generator)
        idx = max(start - 1, 0)
        return videos[idx:end]
    except Exception as e:
        print(f"❌ 채널 영상 목록 조회 실패: {e}")
        return []
