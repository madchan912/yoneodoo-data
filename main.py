import os
import json
import re
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR
from openai import OpenAI

# 1. 환경변수 불러오기
load_dotenv()

# 2. 로컬 LLM(Ollama) 세팅
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"  
)

def get_db_connection():
    try:
        return psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            port=os.environ.get("DB_PORT"),
            dbname=os.environ.get("DB_NAME"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD")
        )
    except Exception as e:
        print(f"❌ DB 접속 실패: {e}")
        return None

def extract_video_id(url):
    match = re.search(r"(?:v=|\/shorts\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url)
    if match:
        return match.group(1)
    return None

def extract_recipe_with_llm(transcript_text, comments_text):
    print("🤖 맥북 로컬 AI가 자막과 고정 댓글을 정밀 분석 중입니다...")
    
    prompt = f"""
    너는 요리 레시피 전문 분석가야. 
    제공된 '자막'과 '댓글'을 모두 읽고 요리 재료 목록을 추출해줘.
    
    [미션]
    1. 자막에 나오는 메인 재료를 모두 포함할 것.
    2. 특히 '댓글'에 적힌 소스(양념) 비율 정보를 절대 놓치지 말고 모든 소스 재료(마요네즈, 알룰로스, 레몬즙, 파슬리, 스리라차 등)를 ingredients에 넣을 것.
    3. 중복된 재료는 하나만 적을 것.
    4. 결과는 반드시 아래 JSON 형식으로만 출력하고 다른 설명은 하지 마.
    
    [형식]
    {{"recipe_name": "요리 제목", "ingredients": ["재료1", "재료2", "..."]}}
    
    [데이터]
    - 자막: {transcript_text[:2000]} 
    - 댓글: {comments_text[:1500]}
    """
    
    try:
        response = client.chat.completions.create(
            model="llama3.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        
        raw_text = response.choices[0].message.content.strip()
        
        # 🛡️ [방어 로직] AI가 앞뒤에 헛소리를 붙여도 JSON만 쏙 골라내는 정규식
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            print("⚠️ AI 답변에서 JSON 형식을 찾을 수 없습니다.")
            return {"recipe_name": "분석 실패", "ingredients": []}

    except Exception as e:
        print(f"❌ AI 분석 에러: {e}")
        return {"recipe_name": "에러 발생", "ingredients": []}

def process_youtube_recipe(video_id, original_url):
    print(f"🚀 영상 ID({video_id}) 수집 시작...")
    
    conn = get_db_connection()
    if not conn: return
    cur = conn.cursor()
    
    try:
        # 중복 체크 (테스트를 위해 기존 데이터가 있으면 삭제 후 재진행)
        cur.execute("DELETE FROM recipes WHERE video_id = %s", (video_id,))
        
        # 1. 자막 추출
        ytt_api = YouTubeTranscriptApi()
        transcript_data = ytt_api.fetch(video_id, languages=['ko', 'en']).to_raw_data()
        transcript_text = " ".join([t['text'] for t in transcript_data])
        
        # 2. 댓글 추출 (고정 댓글 포함 10개)
        downloader = YoutubeCommentDownloader()
        comment_generator = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)
        comments_text = ""
        count = 0
        for comment in comment_generator:
            comments_text += comment['text'] + "\n"
            count += 1
            if count >= 10: break

        # 3. AI 분석
        recipe_data = extract_recipe_with_llm(transcript_text, comments_text)
        
        if not recipe_data.get("ingredients"):
            print("⚠️ 추출된 재료가 없어 저장을 건너뜁니다.")
            return

        # 4. DB 저장
        current_time = datetime.now()
        cur.execute("""
            INSERT INTO recipes (video_id, title, youtube_url, ingredients, created_at) 
            VALUES (%s, %s, %s, %s, %s)
        """, (video_id, recipe_data['recipe_name'], original_url, json.dumps(recipe_data['ingredients'], ensure_ascii=False), current_time))
        
        conn.commit()
        print(f"🎯 [{recipe_data['recipe_name']}] 저장 완료! (추출된 재료: {', '.join(recipe_data['ingredients'])})")

    except Exception as e:
        print(f"❌ 처리 에러: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    test_url = "https://www.youtube.com/shorts/qgmdgz_M-xs" 
    video_id = extract_video_id(test_url)
    if video_id:
        process_youtube_recipe(video_id, test_url)