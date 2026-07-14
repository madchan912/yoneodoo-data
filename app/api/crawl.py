import uuid
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.pipeline import run_channel_crawl, run_single_video

router = APIRouter()

# 인메모리 job 상태 저장소 (서버 재시작 시 초기화됨)
jobs: dict[str, dict] = {}


class CrawlRequest(BaseModel):
    channel_url: str
    start: int = 1
    end: int = 50


@router.post("/crawl")
def start_crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "channel_url": req.channel_url,
        "total": req.end - req.start + 1,
        "processed": 0,
        "results": {
            "SUCCESS": 0,
            "NEEDS_REVIEW": 0,
            "NO_SUBTITLES": 0,
            "AI_ERROR": 0,
            "SKIP": 0,
        },
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "error": None,
    }
    background_tasks.add_task(
        run_channel_crawl, req.channel_url, req.start, req.end, job_id, jobs
    )
    return {"job_id": job_id, "status": "pending"}


@router.get("/status/{job_id}")
def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return {"error": "job not found", "job_id": job_id}
    return job


class CrawlVideoRequest(BaseModel):
    video_url: str
    youtuber_name: str = ""


@router.post("/crawl/video")
def start_crawl_video(req: CrawlVideoRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "video_url": req.video_url,
        "total": 1,
        "processed": 0,
        "results": {
            "SUCCESS": 0,
            "NEEDS_REVIEW": 0,
            "NO_SUBTITLES": 0,
            "AI_ERROR": 0,
            "SKIP": 0,
        },
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "error": None,
    }
    background_tasks.add_task(run_single_video, req.video_url, req.youtuber_name, job_id, jobs)
    return {"job_id": job_id, "status": "pending"}


@router.get("/health")
def health():
    return {"status": "ok"}
