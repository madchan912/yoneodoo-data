import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
import os

# Windows cp949 콘솔에서 이모지 포함 로그가 깨지는 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.api.crawl import router as crawl_router
from app.api.batch import router as batch_router
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="YoNeoDoo Data Pipeline", version="2.0.0", lifespan=lifespan)
app.include_router(crawl_router)
app.include_router(batch_router)
