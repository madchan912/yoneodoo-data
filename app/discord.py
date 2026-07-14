import os
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_batch_report(results: dict, channel_url: str = "") -> None:
    """배치 결과를 Discord 웹훅으로 전송한다. (구현 예정)"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK_URL 미설정, 알림 스킵")
        return

    # TODO: 배치 결과 임베드 메시지 작성 후 전송
    print(f"📢 Discord 알림 (미구현): {results}")
