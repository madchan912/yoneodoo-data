import yt_dlp


def get_description(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("description", "") or ""
    except Exception as e:
        print(f"    ⚠️ description 추출 실패: {e}")
        return ""
