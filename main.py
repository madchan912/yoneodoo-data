import os
import json
import re
import time
import random
import psycopg2
import scrapetube
import traceback
from datetime import datetime
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR
from openai import OpenAI

# venv 환경 실행 명령어
# source venv/bin/activate

load_dotenv()

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
    timeout=180.0
)

# -------------------------------------------------
# DB 연결
# -------------------------------------------------
def get_db_connection():
    try:
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5433"),
            dbname=os.environ.get("DB_NAME", "yoneodoo"),
            user=os.environ.get("DB_USER", "root"),
            password=os.environ.get("DB_PASSWORD", "1234")
        )
    except Exception as e:
        print("❌ DB 접속 실패:", e)
        return None

# -------------------------------------------------
# 자막 추출 (V1.2.4 최신)
# -------------------------------------------------
def get_transcript_safe(video_id):
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        transcript = None

        try:
            transcript = transcript_list.find_manually_created_transcript(['ko','ko-KR'])
            print("    ✅ 수동 한국어 자막 발견")
        except:
            try:
                transcript = transcript_list.find_generated_transcript(['ko','ko-KR'])
                print("    ✅ 자동 한국어 자막 발견")
            except:
                try:
                    transcript = transcript_list.find_transcript(['en'])
                    print("    ⚠️ 영어 자막 발견 (AI 번역 진행)")
                except:
                    print("    ❌ 사용 가능한 자막 없음")
                    return ""

        if transcript is None:
            return ""

        transcript_data = transcript.fetch()
        transcript_text = " ".join([t.text for t in transcript_data])
        return transcript_text

    except Exception as e:
        print(f"    ❌ 자막 추출 완전 실패: {type(e).__name__} - {e}")
        return ""

# -------------------------------------------------
# 댓글 하나만 가져오기
# -------------------------------------------------
def get_top_comment(video_id):
    try:
        downloader = YoutubeCommentDownloader()
        comments = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)
        for comment in comments:
            return comment['text']
    except Exception as e:
        print("    ⚠️ 댓글 수집 실패")
    return ""

# -------------------------------------------------
# LLM 분석 (외계어 방지용 깔끔한 프롬프트)
# -------------------------------------------------
def extract_recipe_with_llm(transcript_text, comments_text):
    prompt = f"""
너는 요리 레시피 데이터를 JSON으로 변환하는 AI야.
아래 자막과 댓글을 읽고, 요리 이름과 재료 목록을 완벽한 JSON 형식으로만 대답해. 부가 설명은 절대 하지 마.

[지시사항]
1. 재료는 'name(이름)'과 'amount(수량과 단위)' 두 가지로만 적어.
2. amount에는 반드시 숫자와 단위(스푼, 개, g 등)를 같이 적어. (예: "0.5스푼", "1개")
3. 원본에 단위 없이 숫자만 있다면, 요리 문맥을 파악해서 "스푼" 등을 알아서 붙여줘.

[출력 예시]
{{
  "recipe_name": "요리이름",
  "ingredients": [
    {{"name": "고추장", "amount": "0.5스푼"}},
    {{"name": "케첩", "amount": "1스푼"}}
  ]
}}

[데이터]
자막: {transcript_text[:2000]}
댓글: {comments_text}
"""
    try:
        print("    👉 AI 분석 요청 (외계어 방지 심플 프롬프트 적용...)")
        response = client.chat.completions.create(
            model="llama3.1",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1,
            timeout=180.0
        )
        raw = response.choices[0].message.content
        
        print(f"    [DEBUG] AI 원본 응답 미리보기: {raw[:100].replace(chr(10), ' ')}...")
        
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print("    ❌ AI 분석 실패:", e)

    return {"recipe_name":"AI 실패", "ingredients":[]}

# -------------------------------------------------
# 영상 처리
# -------------------------------------------------
def process_youtube_recipe(video_id, url):
    print(f"\n▶ 영상 분석 시작: {video_id}")
    conn = get_db_connection()
    if not conn:
        return
    cur = conn.cursor()

    try:
        # DB 에러 방지용 체크 (성공/실패 무조건 스킵)
        cur.execute("SELECT status FROM recipes WHERE video_id=%s", (video_id,))
        row = cur.fetchone()

        if row:
            print(f"⏩ 이미 처리된 영상 스킵 (상태: {row[0]})")
            return "SKIP"

        status = "SUCCESS"
        transcript_text = ""
        comments_text = ""

        print("  ▶ 자막 수집")
        transcript_text = get_transcript_safe(video_id)
        if transcript_text == "":
            status = "NO_SUBTITLES"

        if status == "SUCCESS":
            print("  ▶ 댓글 수집")
            comments_text = get_top_comment(video_id)
            print("  ▶ AI 분석")
            result = extract_recipe_with_llm(transcript_text, comments_text)
            recipe_name = result.get("recipe_name","레시피")
            ingredients = result.get("ingredients",[])
            if not ingredients:
                status = "AI_ERROR"
        else:
            recipe_name = "자막 없음"
            ingredients = []

        print("  ▶ DB 저장")
        cur.execute("""
        INSERT INTO recipes
        (video_id,title,youtube_url,ingredients,created_at,status)
        VALUES (%s,%s,%s,%s,%s,%s)
        """, (video_id, recipe_name, url, json.dumps(ingredients,ensure_ascii=False), datetime.now(), status))
        conn.commit()
        print(f"  🎯 완료: [{recipe_name}] 재료 {len(ingredients)}개 적재 성공!")

    except Exception as e:
        print("❌ 영상 처리 실패")
        print(traceback.format_exc())
    finally:
        cur.close()
        conn.close()

# -------------------------------------------------
# 채널 탐색 (배치 처리 적용)
# -------------------------------------------------
def process_channel_videos(channel_url, start=1, end=100):
    print(f"🔍 채널 탐색 시작: {channel_url}")
    
    try:
        # 🚀 에러의 원인이었던 '영상 목록 가져오기' 코드 복구!
        generator = scrapetube.get_channel(channel_url=channel_url, content_type="shorts")
        videos = list(generator)
    except Exception as e:
        print("❌ 채널 영상 목록을 가져오는 데 실패했습니다:", e)
        return
        
    # start ~ end 구간만큼 자르기
    target_videos = videos[start - 1 : end]
    
    processed = 0
    total_targets = len(target_videos)
    
    for video in target_videos:
        video_id = video.get("videoId") 
        if not video_id:
            continue
            
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        print("\n======================================")
        current_num = start + processed
        print(f"🎬 전체 {current_num}번째 영상 처리 중 (이번 작업: {processed+1}/{total_targets})")
        print("======================================")
        
        status = process_youtube_recipe(video_id, url) 
        processed += 1
        
        if status == "SKIP":
            continue
        
        sleep_time = random.uniform(20, 40)
        print(f"⏳ {sleep_time:.1f}초 대기 중...")
        time.sleep(sleep_time)

# -------------------------------------------------
# 실행
# -------------------------------------------------
if __name__ == "__main__":
    channel = "https://www.youtube.com/@유지만"
    
    # 여기서 1, 100 / 101, 200 등 원하는 구간을 입력하세요!
    process_channel_videos(channel, 1, 50)