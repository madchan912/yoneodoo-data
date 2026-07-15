import os
import requests
from datetime import datetime

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_batch_report(summary: dict) -> None:
    """배치 결과 요약을 Discord 웹훅 임베드로 전송합니다. DISCORD_WEBHOOK_URL 미설정 시 스킵."""
    if not summary or summary.get("youtuber_count", 0) == 0:
        print("⚠️ [Discord] 배치 이력 없음, 전송 스킵")
        return

    if not DISCORD_WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK_URL 미설정, 알림 스킵")
        return

    date = summary.get("date", datetime.now().strftime("%Y-%m-%d"))
    youtuber_count = summary.get("youtuber_count", 0)
    total = summary.get("total_processed", 0)
    success = summary.get("SUCCESS", 0)
    needs_review = summary.get("NEEDS_REVIEW", 0)
    no_subtitles = summary.get("NO_SUBTITLES", 0)
    ai_error = summary.get("AI_ERROR", 0)
    skip = summary.get("SKIP", 0)
    blocked = summary.get("blocked", 0)
    failed = summary.get("failed", 0)

    # 차단 시 빨강, 실패 있으면 주황, 정상이면 초록
    if blocked > 0:
        color = 0xFF0000
    elif failed > 0:
        color = 0xFF9900
    else:
        color = 0x00C851

    embed = {
        "title": f"🍳 요너두 배치 크롤링 리포트 — {date}",
        "color": color,
        "fields": [
            {"name": "📺 처리 유튜버", "value": f"{youtuber_count}명", "inline": True},
            {"name": "🎬 총 처리 영상", "value": f"{total}개", "inline": True},
            {"name": "​", "value": "​", "inline": True},
            {"name": "✅ SUCCESS", "value": str(success), "inline": True},
            {"name": "🔍 NEEDS_REVIEW", "value": str(needs_review), "inline": True},
            {"name": "🔇 NO_SUBTITLES", "value": str(no_subtitles), "inline": True},
            {"name": "❌ AI_ERROR", "value": str(ai_error), "inline": True},
            {"name": "⏩ SKIP", "value": str(skip), "inline": True},
            {"name": "⛔ BLOCKED", "value": str(blocked), "inline": True},
        ],
        "footer": {"text": "yoneodoo-data 자동 배치"},
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    if failed > 0:
        embed["fields"].append({"name": "💀 FAILED", "value": str(failed), "inline": True})

    youtubers = summary.get("youtubers", [])
    if youtubers:
        lines = []
        for y in youtubers:
            yname = y.get("name", "?")
            ystatus = y.get("status")
            r = y.get("results", {})
            if ystatus == "blocked":
                lines.append(f"⛔ {yname}: BLOCKED (크롤링 중단)")
            elif ystatus == "failed":
                lines.append(f"💀 {yname}: FAILED")
            else:
                parts = [
                    f"{k} {r[k]}" for k in ("SUCCESS", "NEEDS_REVIEW", "NO_SUBTITLES", "AI_ERROR")
                    if r.get(k, 0) > 0
                ]
                lines.append(f"✅ {yname}: {' / '.join(parts) if parts else 'SKIP'}")
        embed["fields"].append({
            "name": "📋 유튜버별 결과",
            "value": "\n".join(lines)[:1024],
            "inline": False,
        })

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
        if res.status_code in (200, 204):
            print("✅ Discord 알림 전송 완료")
        else:
            print(f"❌ Discord 웹훅 오류: {res.status_code} {res.text[:200]}")
    except Exception as e:
        print(f"❌ Discord 전송 실패: {e}")
