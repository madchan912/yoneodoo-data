import os
import json
import re
import time
import random
import urllib.parse # 🚀 URL에서 유튜버 이름(한글)을 예쁘게 뽑아오기 위한 라이브러리 추가
import requests
import scrapetube
import traceback
from datetime import datetime
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_POPULAR
from openai import OpenAI

# venv 환경 실행 명령어
# source venv/bin/activate

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
    timeout=180.0
)

_DEFAULT_RECIPES_API = "http://localhost:8080/api/v1/recipes"


def _resolve_recipes_api_base_url() -> str:
    """
    .env 또는 환경 변수 API_BASE_URL.
    - 레시피 목록 GET / POST 모두 동일 베이스 URL 사용 (…/api/v1/recipes).
    - 비어 있으면 로컬 기본값 사용.
    """
    raw = os.environ.get("API_BASE_URL", "").strip()
    if not raw:
        print(f"ℹ️  API_BASE_URL 미설정 → 로컬 기본값 사용: {_DEFAULT_RECIPES_API}")
        return _DEFAULT_RECIPES_API
    return raw.rstrip("/")


API_BASE_URL = _resolve_recipes_api_base_url()


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
# LLM 분석 (외계어 방지 및 띄어쓰기 금지 프롬프트)
# -------------------------------------------------
def extract_recipe_with_llm(transcript_text, comments_text):
    prompt = f"""
너는 요리 레시피 데이터를 JSON으로 변환하는 AI야.
아래 자막과 댓글을 읽고, 요리 이름과 재료 목록을 완벽한 JSON 형식으로만 대답해. 부가 설명은 절대 하지 마.

[지시사항]
1. 재료는 'name(이름)'과 'amount(수량과 단위)' 두 가지로만 적어.
2. amount에는 반드시 숫자와 단위(스푼, 개, g 등)를 같이 적어. (예: "0.5스푼", "1개")
3. 원본에 단위 없이 숫자만 있다면, 요리 문맥을 파악해서 "스푼" 등을 알아서 붙여줘.
4. name(이름)에는 절대 띄어쓰기를 포함하지 마. 모든 단어를 붙여서 적어. (예: "저당 고추장" -> "저당고추장", "다진 마늘" -> "다진마늘")

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
        print("    👉 AI 분석 요청 중...")
        response = client.chat.completions.create(
            model="llama3.1",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1,
            timeout=180.0
        )
        raw = response.choices[0].message.content
        
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print("    ❌ AI 분석 실패:", e)

    return {"recipe_name":"AI 실패", "ingredients":[]}

# -------------------------------------------------
# 영상 처리 (API 통신 방식)
# -------------------------------------------------
# 🚀 파라미터에 youtuber_name을 추가로 받도록 수정
def process_youtube_recipe(video_id, url, existing_videos, youtuber_name):
    print(f"\n▶ 영상 분석 시작: {video_id}")
    
    if video_id in existing_videos:
        print(f"⏩ 이미 처리된 영상 스킵 (DB에 존재함)")
        return "SKIP"

    try:
        status = "SUCCESS"
        
        print("  ▶ 자막 수집")
        transcript_text = get_transcript_safe(video_id)
        if transcript_text == "":
            status = "NO_SUBTITLES"

        if status == "SUCCESS":
            print("  ▶ 댓글 수집")
            comments_text = get_top_comment(video_id)
            print("  ▶ AI 분석")
            result = extract_recipe_with_llm(transcript_text, comments_text)
            recipe_name = result.get("recipe_name", "레시피")
            ingredients = result.get("ingredients", [])
            if not ingredients:
                status = "AI_ERROR"
        else:
            recipe_name = "자막 없음"
            ingredients = []

        print("  ▶ 백엔드 API로 데이터 전송")
        payload = {
            "videoId": video_id,
            "title": recipe_name,
            "youtubeUrl": url,
            "status": status,
            "transcript": transcript_text,
            "ingredients": ingredients,
            "youtuberName": youtuber_name  # 🚀 채널 탐색 함수에서 넘겨준 유튜버 이름 안착!
        }

        # 🚀 백엔드 API로 POST 요청
        response = requests.post(API_BASE_URL, json=payload)
        
        if response.status_code == 200:
            print(f"  🎯 완료: [{recipe_name}] 재료 {len(ingredients)}개 적재 성공! (유튜버: {youtuber_name})")
        else:
            print(f"  ❌ API 에러 응답: {response.status_code} - {response.text}")
            status = "API_ERROR"

        return status

    except requests.exceptions.ConnectionError:
        print("  ❌ 백엔드 서버에 연결할 수 없습니다. Spring Boot 서버가 켜져 있는지 확인하세요.")
        return "CONNECTION_ERROR"
    except Exception as e:
        print("❌ 영상 처리 실패")
        print(traceback.format_exc())
        return "ERROR"

# -------------------------------------------------
# 채널 탐색 (배치 처리 적용)
# -------------------------------------------------
def process_channel_videos(channel_url, start=1, end=100):
    print(f"🔍 채널 탐색 시작: {channel_url}")
    
    # 🚀 URL에서 '@' 뒤의 유튜버 이름만 쏙 뽑아냅니다. (한글 인코딩 처리 포함)
    youtuber_name = "알 수 없음"
    if '@' in channel_url:
        extracted = channel_url.split('@')[-1]
        youtuber_name = urllib.parse.unquote(extracted).replace('/', '') # 한글 깨짐 및 슬래시 방지
    print(f"🧑‍🍳 추출된 유튜버 이름: {youtuber_name}")
    
    # 1. 백엔드에서 이미 처리된 영상 ID 목록을 먼저 가져옵니다.
    existing_videos = set()
    try:
        print("📡 백엔드에서 기존 레시피 목록을 불러오는 중...")
        res = requests.get(API_BASE_URL)
        if res.status_code == 200:
            existing_videos = {recipe['videoId'] for recipe in res.json() if recipe.get('videoId')}
            print(f"✅ 기존 데이터 {len(existing_videos)}개 확인 완료 (해당 영상들은 스킵됩니다).")
    except Exception as e:
        print("⚠️ 백엔드 기존 데이터 조회 실패 (모두 새로 처리합니다).")
    
    try:
        generator = scrapetube.get_channel(channel_url=channel_url, content_type="shorts")
        videos = list(generator)
    except Exception as e:
        print("❌ 채널 영상 목록을 가져오는 데 실패했습니다:", e)
        return
        
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
        
        # 🚀 여기서 추출한 youtuber_name을 던져줍니다!
        status = process_youtube_recipe(video_id, url, existing_videos, youtuber_name) 
        processed += 1
        
        if status in ("SKIP", "CONNECTION_ERROR"):
            continue
        
        sleep_time = random.uniform(20, 40)
        print(f"⏳ {sleep_time:.1f}초 대기 중...")
        time.sleep(sleep_time)

# -------------------------------------------------
# 실행
# -------------------------------------------------
if __name__ == "__main__":
    # 🚀 config.json에서 설정값 불러오기
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        TARGET_CHANNEL_URL = config.get("target_channel_url", "https://www.youtube.com/@유지만")
        START_INDEX = config.get("start_index", 1)
        END_INDEX = config.get("end_index", 10)
        
    except FileNotFoundError:
        print("⚠️ config.json 파일을 찾을 수 없어 기본값으로 실행합니다.")
        TARGET_CHANNEL_URL = "https://www.youtube.com/@유지만"
        START_INDEX = 1
        END_INDEX = 10
    except Exception as e:
        print(f"⚠️ 설정 파일 로드 에러: {e}")
        exit()

    print(f"📺 대상 채널: {TARGET_CHANNEL_URL}")
    print(f"🔢 처리 구간: {START_INDEX} ~ {END_INDEX}")
    
    process_channel_videos(TARGET_CHANNEL_URL, START_INDEX, END_INDEX)