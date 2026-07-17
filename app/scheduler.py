import os
import uuid
from datetime import datetime

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.pipeline import run_channel_crawl
from app.api.crawl import jobs
from app import discord

_scheduler = BackgroundScheduler()

SPRING_API_BASE = os.environ.get("SPRING_API_BASE_URL", "http://localhost:8080")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# 마지막 배치 결과 — 오전 7시 Discord 리포트에서 소비
_last_batch_summary: dict | None = None


def _fetch_active_youtubers() -> list[dict]:
    """Spring Boot API에서 is_active=true 유튜버 목록을 조회합니다."""
    url = f"{SPRING_API_BASE}/api/v1/admin/youtubers"
    res = requests.get(url, headers={"X-Admin-Secret": ADMIN_SECRET}, timeout=10)
    res.raise_for_status()
    return [y for y in res.json() if y.get("active") is True]


def _batch_crawl() -> None:
    """매일 새벽 3시: 활성 유튜버 전체를 순차 크롤링하고 결과를 저장합니다."""
    global _last_batch_summary
    print(f"\n🕒 [배치] {datetime.now().strftime('%Y-%m-%d %H:%M')} 자동 크롤링 시작")

    try:
        youtubers = _fetch_active_youtubers()
    except Exception as e:
        print(f"❌ [배치] 유튜버 목록 조회 실패: {e}")
        return

    if not youtubers:
        print("⚠️ [배치] 활성 유튜버 없음, 스킵")
        return

    print(f"📋 [배치] 활성 유튜버 {len(youtubers)}명 순차 크롤링 시작")

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

    for y in youtubers:
        channel_url = y.get("channelUrl", "")
        name = y.get("youtuberName", "?")
        if not channel_url:
            continue

        job_id = str(uuid.uuid4())
        jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "channel_url": channel_url,
            "total": 50,
            "total_videos": 0,
            "processed": 0,
            "results": {
                "SUCCESS": 0,
                "INCOMPLETE": 0,
                "NO_SUBTITLES": 0,
                "AI_ERROR": 0,
                "SKIP": 0,
            },
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "error": None,
        }

        print(f"\n🎬 [배치] {name} 크롤링 시작")
        # APScheduler 스레드 안에서 동기 호출 — 한 채널씩 순차 처리
        run_channel_crawl(channel_url, 1, 50, job_id, jobs)

        job = jobs[job_id]
        results = job.get("results", {})
        summary["total_processed"] += job.get("processed", 0)
        for k in ("SUCCESS", "INCOMPLETE", "NO_SUBTITLES", "AI_ERROR", "SKIP"):
            summary[k] += results.get(k, 0)

        status = job.get("status")
        summary["youtubers"].append({
            "name": name,
            "status": status,
            "results": dict(results),
        })

        if status == "blocked":
            summary["blocked"] += 1
            print(f"⛔ [배치] {name} IP 차단 감지 — 배치 전체 중단")
            break
        elif status == "failed":
            summary["failed"] += 1

    _last_batch_summary = summary
    print(f"\n✅ [배치] 완료: {summary}")


def _discord_report() -> None:
    """매일 오전 7시: 전날 배치 결과를 Discord로 전송합니다."""
    if not _last_batch_summary:
        print("⚠️ [Discord] 당일 배치 이력 없음, 전송 스킵")
        return
    discord.send_batch_report(_last_batch_summary)


def start_scheduler() -> None:
    _scheduler.add_job(_batch_crawl, CronTrigger(hour=3, minute=0), id="batch_crawl")
    _scheduler.add_job(_discord_report, CronTrigger(hour=7, minute=0), id="discord_report")
    _scheduler.start()
    print("✅ 스케줄러 시작 (매일 03:00 배치, 07:00 Discord 리포트)")


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown()
        print("🛑 스케줄러 종료")
