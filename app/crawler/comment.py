from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR


def get_top_comment(video_id: str) -> str:
    try:
        downloader = YoutubeCommentDownloader()
        comments = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)
        for comment in comments:
            return comment.get("text", "")
    except Exception as e:
        print(f"    ⚠️ 댓글 수집 실패: {e}")
    return ""
