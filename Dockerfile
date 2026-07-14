FROM python:3.11-slim

WORKDIR /app

# 라이브러리 먼저 복사해서 Docker 레이어 캐싱 활용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
