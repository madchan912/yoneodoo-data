# 🤖 YoNeoDoo - AI Data Pipeline (Crawler)

유튜브 요리 영상에서 자막을 추출하고, 로컬 LLM(Llama 3.1)을 활용해 레시피 데이터를 정형화(JSON)하여 백엔드 API로 전송하는 인공지능 데이터 파이프라인입니다.

## 🛠 Tech Stack
- **Language**: Python 3.x
- **AI Model**: Llama 3.1 8B (via Ollama)
- **Key Libraries**: `youtube-transcript-api` (자막 추출), `requests` (API 통신)

## 🚀 How to Run (Local)
본 크롤러는 로컬 환경의 자원(GPU/RAM)을 활용하여 LLM을 구동합니다.

1. 로컬 PC(Mac/Windows)에 [Ollama](https://ollama.com/)를 설치하고 모델을 백그라운드에 띄웁니다.
   ```bash
   ollama run llama3.1
   ```
2. 파이썬 가상환경을 세팅하거나, 필요한 의존성 패키지를 설치합니다.
   ```bash
   pip install -r requirements.txt
   ```
3. 크롤러 스크립트를 실행하여 유튜브 데이터를 수집하고 백엔드 API로 전송합니다.
   ```bash
   python main.py
   ```

## 🔐 Environment Variables (.env)
크롤링한 데이터를 적재할 백엔드 **레시피 API 전체 URL**을 환경변수로 둡니다. `main.py`와 같은 폴더에 `.env`를 만들고 값을 넣습니다. (샘플은 `.env.example` 참고)

`API_BASE_URL`이 없거나 비어 있으면 로컬 기본값 `http://localhost:8080/api/v1/recipes`가 사용됩니다.

```env
# 로컬 백엔드 테스트 시
API_BASE_URL=http://localhost:8080/api/v1/recipes

# 운영 서버(Render 등)에 적재 시
# API_BASE_URL=https://yoneodoo-api.onrender.com/api/v1/recipes
```
