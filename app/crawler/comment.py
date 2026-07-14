from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR


def get_top_comment(video_id: str) -> str:
    try:
        downloader = YoutubeCommentDownloader()
        comments = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)
        for comment in comments:
            return comment.get("text", "")
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ('blocked', '429', 'bot', 'captcha', 'sign in to confirm')):
            print(f"    ⛔ 댓글 수집 중 차단 감지: {type(e).__name__}")
            raise
        print(f"    ⚠️ 댓글 수집 실패: {e}")
    return ""
