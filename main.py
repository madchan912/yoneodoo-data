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

def extract_recipe_with_llm(transcript_text, comments_text):
    prompt = f"""
    너는 요리 레시피 전문 분석가야. 
    제공된 '자막'과 '댓글'을 모두 읽고 요리 재료 목록을 추출해줘.
    
    [미션]
    1. 자막에 나오는 메인 재료를 모두 포함할 것.
    2. 특히 '댓글'에 적힌 소스(양념) 비율 정보를 절대 놓치지 말고 모든 소스 재료를 ingredients에 넣을 것.
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
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"recipe_name": "AI 분석 실패", "ingredients": []}
    except Exception as e:
        return {"recipe_name": "AI 에러", "ingredients": []}

def process_youtube_recipe(video_id, original_url):
    print(f"  ▶ 영상 ID({video_id}) 분석 시작...")
    
    conn = get_db_connection()
    if not conn: return
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT id, status FROM recipes WHERE video_id = %s", (video_id,))
        row = cur.fetchone()
        if row:
            if row[1] in ["SUCCESS", "NO_SUBTITLES"]:
                print(f"  ⏩ 이미 처리된 영상입니다. (상태: {row[1]}) 스킵!")
                return
            else:
                print(f"  🔄 이전 실패 건(상태: {row[1]}) 재시도 중...")
                cur.execute("DELETE FROM recipes WHERE video_id = %s", (video_id,))

        status = "SUCCESS"
        transcript_text = ""
        recipe_name = "수기 입력 필요"
        ingredients = []

        try:
            # 🔥 개발자님의 원본 코드(최신 라이브러리 문법)로 다시 롤백했습니다!
            transcript = YouTubeTranscriptApi().fetch(video_id, languages=['ko'])
            transcript_text = " ".join([t['text'] for t in transcript])
            
        except Exception as e:
            error_msg = str(e)
            
            # 🔥 [핵심 수정] 자막이 없을 때 나는 에러 문구("could not retrieve")를 조건에 추가했습니다.
            if "could not retrieve" in error_msg.lower() or "disabled" in error_msg.lower() or "no transcript" in error_msg.lower():
                print(f"  ⚠️ 한국어 자막이 존재하지 않습니다. 상태를 'NO_SUBTITLES'로 저장합니다.")
                status = "NO_SUBTITLES"
            else:
                # 진짜 네트워크 에러일 때만 상세 로그를 출력합니다.
                print("\n  ================ [진짜 봇 차단/네트워크 에러 상세] ================")
                print(traceback.format_exc())
                print("  ==================================================================\n")
                status = "NETWORK_ERROR"

        if status == "SUCCESS":
            try:
                downloader = YoutubeCommentDownloader()
                comment_generator = downloader.get_comments(video_id, sort_by=SORT_BY_POPULAR)
                comments_text = ""
                count = 0
                for comment in comment_generator:
                    comments_text += comment['text'] + "\n"
                    count += 1
                    if count >= 10: break
            except Exception as e:
                print("  ⚠️ 댓글 수집 중 에러 발생 (자막만으로 진행)")
                comments_text = ""

            print("  🤖 자막/댓글 AI 분석 중...")
            recipe_data = extract_recipe_with_llm(transcript_text, comments_text)
            
            if recipe_data.get("ingredients"):
                recipe_name = recipe_data['recipe_name']
                ingredients = recipe_data['ingredients']
            else:
                status = "AI_ERROR"

        current_time = datetime.now()
        cur.execute("""
            INSERT INTO recipes (video_id, title, youtube_url, ingredients, created_at, status) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (video_id, recipe_name, original_url, json.dumps(ingredients, ensure_ascii=False), current_time, status))
        
        conn.commit()
        
        if status == "SUCCESS":
            print(f"  🎯 [{recipe_name}] 완벽 저장 완료!")
        else:
            print(f"  📌 [상태: {status}] 영상 링크만 임시 저장 완료!")

    except Exception as e:
        print(f"  ❌ DB 저장 중 에러: {e}")
    finally:
        cur.close()
        conn.close()

def process_channel_videos(channel_url, max_count=5, content_type="shorts"):
    print(f"\n📺 채널 탐색 시작: {channel_url} (타겟: {content_type})")
    
    try:
        videos = scrapetube.get_channel(channel_url=channel_url, content_type=content_type)
        
        processed = 0
        for video in videos:
            if processed >= max_count:
                print(f"\n✅ 지정한 {max_count}개 영상 처리가 모두 끝났습니다!")
                break
                
            video_id = video['videoId']
            video_url = f"https://www.youtube.com/watch?v={video_id}" 
            
            print(f"\n[{processed + 1}/{max_count}] 번째 영상 ------------------------")
            process_youtube_recipe(video_id, video_url)
            
            processed += 1
            
            sleep_time = random.uniform(8, 15)
            print(f"  ⏳ 봇 차단 방지: {sleep_time:.1f}초 대기 중...")
            time.sleep(sleep_time) 

    except Exception as e:
        print(f"❌ 채널 탐색 중 에러 발생: {e}")

if __name__ == "__main__":
    target_channel_url = "https://www.youtube.com/@유지만" 
    process_channel_videos(target_channel_url, max_count=9999, content_type="shorts")