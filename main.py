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
# LLM 분석 (이름/수량/단위 JSON 객체 분해 적용)
# -------------------------------------------------
def extract_recipe_with_llm(transcript_text, comments_text):
    prompt = f"""
너는 최고 수준의 요리 데이터 엔지니어다.
제공된 자막과 댓글을 읽고 요리 이름과 재료 목록을 추출해라.

[중요 지시사항]
1. 재료 정보를 '이름(name)'과 '수량(amount)' 딱 2가지 속성으로만 분해해서 객체로 만들어라.
2. 수량(amount)에는 반드시!! 숫자와 '단위(스푼, 개, g, 컵 등)'를 함께 적어라. 
3. 🔥원본 텍스트에 "고추장 0.5, 간장 1" 처럼 단위 없이 숫자만 적혀 있더라도, 요리 문맥(비율 등)을 파악해서 무조건 "0.5스푼", "1스푼" 처럼 단위를 붙여서 적어라.
4. 수량 정보가 아예 없다면 빈 문자열("")로 처리해라.
5. 결과는 반드시 아래 JSON 형식으로만 출력하라.

[출력 형식 예시]
{{
"recipe_name": "요리이름",
"ingredients": [
    {{"name": "양파", "amount": "2개"}},
    {{"name": "진간장", "amount": "1.5스푼"}},
    {{"name": "후추", "amount": "약간"}}
]
}}

자막:
{transcript_text[:2000]}

댓글:
{comments_text}
"""
    try:
        print("    👉 AI 분석 요청 (스마트 냉장고용 데이터 분해 중...)")
        response = client.chat.completions.create(
            model="llama3.1",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1
        )
        raw = response.choices[0].message.content
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
        # DB 에러 방지용 체크 (과거 실패 기록 날리기)
        cur.execute("SELECT status FROM recipes WHERE video_id=%s", (video_id,))
        row = cur.fetchone()

        if row:
            if row[0] == "SUCCESS":
                print("⏩ 이미 성공한 영상 스킵")
                return
            else:
                print("🔄 기존 실패 기록 삭제 후 재시도합니다.")
                cur.execute("DELETE FROM recipes WHERE video_id=%s", (video_id,))
                conn.commit()

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
# 채널 탐색
# -------------------------------------------------
def process_channel_videos(channel_url, max_count=10):
    print("\n📺 채널 탐색 시작:", channel_url)
    videos = scrapetube.get_channel(channel_url=channel_url, content_type="shorts")
    processed = 0

    for video in videos:
        if processed >= max_count:
            break
        video_id = video.get("videoId")
        if not video_id:
            continue
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        print("\n======================================")
        print(f"🎬 {processed+1}/{max_count}")
        print("======================================")
        
        process_youtube_recipe(video_id, url)
        processed += 1
        
        sleep = random.uniform(8,15)
        print(f"⏳ {sleep:.1f}초 대기")
        time.sleep(sleep)

# -------------------------------------------------
# 실행
# -------------------------------------------------
if __name__ == "__main__":
    channel = "https://www.youtube.com/@유지만"
    process_channel_videos(channel, 9999)