from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler()


def _batch_job() -> None:
    """매일 새벽 3시 자동 크롤링 배치. (구현 예정)

    TODO:
    - watched_youtubers 테이블에서 활성 채널 목록 조회
    - 각 채널에 대해 신규 영상 크롤링 실행
    - 완료 후 discord.send_batch_report() 호출
    """
    print("🕒 [배치] 새벽 3시 자동 크롤링 시작 (미구현)")


def start_scheduler() -> None:
    _scheduler.add_job(_batch_job, CronTrigger(hour=3, minute=0))
    _scheduler.start()
    print("✅ 스케줄러 시작 (매일 03:00 배치)")


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown()
        print("🛑 스케줄러 종료")
