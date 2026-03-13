# 1. 가볍고 빠른 파이썬 3.11 slim 버전을 사용합니다.
FROM python:3.11-slim

# 2. 컨테이너 안의 작업 폴더를 /app 으로 잡습니다.
WORKDIR /app

# 3. [운영 최적화] 라이브러리 목록 파일(requirements.txt)을 먼저 복사합니다.
# (소스코드보다 이걸 먼저 복사해야 도커의 '레이어 캐싱'을 타서 다음 빌드 속도가 엄청 빨라집니다)
COPY requirements.txt .

# 4. 도커 안에서 라이브러리들을 설치합니다.
# (--no-cache-dir은 찌꺼기를 안 남겨서 도커 용량을 확 줄여주는 데브옵스 필수 팁입니다!)
RUN pip install --no-cache-dir -r requirements.txt

# 5. 나머지 파이썬 소스 코드(main.py 등)를 전부 도커 안으로 복사합니다.
COPY . .

# 6. 도커 컨테이너가 켜질 때 이 명령어로 파이썬 크롤러를 실행합니다.
CMD ["python", "main.py"]