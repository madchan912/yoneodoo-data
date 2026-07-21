import os
import uuid
import threading
from datetime import datetime, timezone

import requests
from fastapi import APIRouter

from app.pipeline import run_channel_crawl
from app import discord

router = APIRouter()

SPRING_API_BASE = os.environ.get("SPRING_API_BASE_URL", "http://localhost:8080")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# 인메모리 배치 job 상태 저장소 (서버 재시작 시 초기화됨)
batch_jobs: dict[str, dict] = {}


def _fetch_active_youtubers() -> list[dict]:
    """Spring Boot API에서 is_active=true 유튜버 목록을 조회합니다."""
    url = f"{SPRING_API_BASE}/api/v1/admin/youtubers"
    res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
    res.raise_for_status()
    return [y for y in res.json() if y.get("active") is True]


def _run_batch(job_id: str) -> None:
    """활성 유튜버 전체를 순차 크롤링합니다.

    EC2 자동 배치(03:00)가 YouTube IP 차단으로 불가능해진 뒤 로컬 PC에서 수동 실행하는 용도입니다.
    유튜버별 진행 상황을 job에 갱신하고, 완료 시 Discord 리포트를 보냅니다.
    """
    job = batch_jobs[job_id]
    job["status"] = "running"

    try:
        youtubers = _fetch_active_youtubers()
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"유튜버 목록 조회 실패: {e}"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        return

    job["total_youtubers"] = len(youtubers)

    if not youtubers:
        job["status"] = "done"
        job["error"] = "활성 유튜버 없음"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        return

    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "youtuber_count": len(youtubers),
        "total_processed": 0,
        "SUCCESS": 0,
        "INCOMPLETE": 0,
        "NO_SUBTITLES": 0,
        "AI_ERROR": 0,
        "SKIP": 0,
        "blocked": 0,
        "failed": 0,
        "youtubers": [],
    }

    inner_jobs: dict[str, dict] = {}

    for y in youtubers:
        channel_url = y.get("channelUrl", "")
        name = y.get("youtuberName", "?")
        if not channel_url:
            continue

        job["current_youtuber"] = name
        print(f"\n🎬 [수동배치] {name} 크롤링 시작")

        inner_job_id = str(uuid.uuid4())
        inner_jobs[inner_job_id] = {
            "job_id": inner_job_id,
            "status": "pending",
            "channel_url": channel_url,
            "total": 0,
            "total_videos": 0,
            "processed": 0,
            "results": {"SUCCESS": 0, "INCOMPLETE": 0, "NO_SUBTITLES": 0, "AI_ERROR": 0, "SKIP": 0},
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "error": None,
        }

        # youtuber_name은 watched_youtubers 등록명 그대로 사용(URL 파싱 아님)
        run_channel_crawl(channel_url, 1, 999, inner_job_id, inner_jobs, youtuber_name=name)

        inner = inner_jobs[inner_job_id]
        results = inner.get("results", {})
        summary["total_processed"] += inner.get("processed", 0)
        for k in ("SUCCESS", "INCOMPLETE", "NO_SUBTITLES", "AI_ERROR", "SKIP"):
            summary[k] += results.get(k, 0)

        status = inner.get("status")
        summary["youtubers"].append({"name": name, "status": status, "results": dict(results)})
        job["completed_youtubers"] += 1

        if status == "blocked":
            summary["blocked"] += 1
            job["status"] = "blocked"
            job["error"] = "IP 차단 감지 — 배치 전체 중단"
            print(f"⛔ [수동배치] {name} IP 차단 감지 — 배치 전체 중단")
            break
        elif status == "failed":
            summary["failed"] += 1

    job["summary"] = summary
    if job["status"] != "blocked":
        job["status"] = "done"
    job["current_youtuber"] = None
    job["finished_at"] = datetime.now(timezone.utc).isoformat()

    print(f"\n✅ [수동배치] 완료: {summary}")
    try:
        discord.send_batch_report(summary)
    except Exception as e:
        print(f"⚠️ Discord 알림 실패: {e}")


@router.post("/batch/run")
def start_batch():
    """활성(is_active=true) 유튜버 전체를 순차 크롤링하는 수동 배치를 즉시 백그라운드로 시작합니다."""
    job_id = str(uuid.uuid4())
    batch_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "total_youtubers": 0,
        "completed_youtubers": 0,
        "current_youtuber": None,
        "summary": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
    }
    thread = threading.Thread(
        target=_run_batch,
        args=(job_id,),
        daemon=True,
        name=f"batch-{job_id[:8]}"
    )
    thread.start()
    return {"job_id": job_id, "message": "배치 시작됨"}


@router.get("/batch/status/{job_id}")
def batch_status(job_id: str):
    job = batch_jobs.get(job_id)
    if not job:
        return {"error": "job not found", "job_id": job_id}
    return job
