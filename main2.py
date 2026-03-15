from youtube_transcript_api import YouTubeTranscriptApi
import traceback

def test_single_video(video_id):
    print(f"\n🎬 [테스트 시작] 영상 ID: {video_id}")
    
    try:
        # 🔥 [핵심] cookies='cookies.txt' 를 추가해서 "나 방금 브라우저로 접속한 사람이야!" 하고 인증합니다.
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, 
            languages=['ko'], 
            cookies='cookies.txt'
        )
        text = " ".join([t['text'] for t in transcript])
        
        print("  ✅ [성공] 쿠키 인증으로 자막 추출 완벽 성공!")
        print(f"  📝 [내용 미리보기]: {text[:100]}...\n")

    except Exception as e:
        error_msg = str(e)
        print("  ❌ [실패] 자막을 가져오지 못했습니다.")
        print(f"  🚨 [실제 에러 메시지]: {error_msg[:150]}...\n")

if __name__ == "__main__":
    # 1번 영상과 개발자님이 최초에 성공했던 2번 영상(치미창가)
    test_videos = ["7q0YMzjPnvo", "qgmdgz_M-xs"]

    for vid in test_videos:
        test_single_video(vid)
        print("-" * 50)