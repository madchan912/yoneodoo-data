import os
import requests
from bs4 import BeautifulSoup
import psycopg2
from dotenv import load_dotenv

# .env 파일에서 DB 정보 불러오기
load_dotenv()

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST"),
            port=os.environ.get("DB_PORT"),
            dbname=os.environ.get("DB_NAME"),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"❌ DB 접속 실패: {e}")
        return None

def test_crawling_and_insert():
    print("🚀 크롤링 및 DB 인서트 테스트 시작...")
    
    # 1. 크롤링 파트
    url = "https://www.naver.com"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.title.string if soup.title else "제목 없음"
    print(f"✅ 크롤링 성공: 가져온 데이터 -> '{title}'")

    # 2. DB 인서트 파트
    conn = get_db_connection()
    if conn:
        print("✅ DB 접속 성공! 데이터 저장을 시작합니다...")
        cur = conn.cursor()
        
        # 테이블이 없으면 만들기 (id, 제목, 수집시간)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crawling_data (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 크롤링한 데이터(네이버 제목)를 테이블에 집어넣기!
        cur.execute("INSERT INTO crawling_data (title) VALUES (%s)", (title,))
        
        # 변경사항 확정(Commit)
        conn.commit()
        
        cur.close()
        conn.close()
        print("🎯 DB 테이블 생성 및 인서트(저장) 완벽하게 성공!")

if __name__ == "__main__":
    test_crawling_and_insert()