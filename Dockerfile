# 1. 가볍고 빠른 파이썬 3.11 리눅스 컴퓨터를 빌려옵니다.
FROM python:3.11-slim

# 2. 컨테이너 안의 작업 폴더를 /app 으로 잡습니다.
WORKDIR /app

# 3. 마법의 종이표(requirements.txt)를 먼저 컨테이너 안으로 복사합니다.
COPY requirements.txt .

# 4. 종이표를 보고 도커 안에서 라이브러리들을 싹 다 설치합니다.
# (--no-cache-dir은 찌꺼기를 안 남겨서 도커 용량을 확 줄여주는 데브옵스 꿀팁입니다!)
RUN pip install --no-cache-dir -r requirements.txt

# 5. 나머지 파이썬 코드(main.py 등)를 전부 도커 안으로 복사합니다.
COPY . .

# 6. 도커 컨테이너가 켜질 때 이 명령어로 파이썬 크롤러를 실행합니다!
CMD ["python", "main.py"]