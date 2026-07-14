from youtube_transcript_api import YouTubeTranscriptApi


def get_transcript(video_id: str) -> str:
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        transcript = None

        try:
            transcript = transcript_list.find_manually_created_transcript(['ko', 'ko-KR'])
            print("    ✅ 수동 한국어 자막 발견")
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(['ko', 'ko-KR'])
                print("    ✅ 자동 한국어 자막 발견")
            except Exception:
                try:
                    transcript = transcript_list.find_transcript(['en'])
                    print("    ⚠️ 영어 자막 발견 (그대로 사용)")
                except Exception:
                    print("    ❌ 사용 가능한 자막 없음")
                    return ""

        if transcript is None:
            return ""

        data = transcript.fetch()
        return " ".join([t.text for t in data])

    except Exception as e:
        if type(e).__name__ == 'RequestBlocked':
            print(f"    ⛔ IP 차단 감지 (RequestBlocked) — 상위로 전파")
            raise
        print(f"    ❌ 자막 추출 실패: {type(e).__name__} - {e}")
        return ""
