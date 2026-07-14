"""
Discord 웹훅 테스트 스크립트.

.env.data.prod에서 DISCORD_WEBHOOK_URL을 읽어 더미 배치 리포트를 전송합니다.

실행:
  python3 test_discord.py
  python3 test_discord.py /path/to/.env.data.prod   # env 파일 경로 직접 지정
"""

import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def load_env_file(path: str) -> None:
    """단순 key=value 형식의 .env 파일을 환경변수로 로드합니다."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# env 파일 경로 결정 — 인자 > 스크립트 옆 .env.data.prod > 홈 디렉터리
if len(sys.argv) > 1:
    env_path = sys.argv[1]
else:
    script_dir = Path(__file__).parent
    candidates = [
        script_dir / ".env.data.prod",
        Path.home() / ".env.data.prod",
    ]
    env_path = next((str(p) for p in candidates if p.exists()), None)

if env_path and Path(env_path).exists():
    load_env_file(env_path)
    print(f"✅ env 로드: {env_path}")
else:
    print(f"⚠️  .env.data.prod 파일을 찾지 못했습니다. 환경변수에서 직접 읽습니다.")

# 로드 후 import — DISCORD_WEBHOOK_URL이 os.environ에 있어야 discord.py가 읽음
sys.path.insert(0, str(Path(__file__).parent))
from app.discord import send_batch_report, DISCORD_WEBHOOK_URL

if not DISCORD_WEBHOOK_URL:
    print("❌ DISCORD_WEBHOOK_URL이 설정되어 있지 않습니다.")
    print("   .env.data.prod 파일에 DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... 를 추가하세요.")
    sys.exit(1)

print(f"🔗 웹훅 URL: {DISCORD_WEBHOOK_URL[:60]}...")
print("📨 테스트 메시지 전송 중...")

send_batch_report({
    "date": "2026-07-15 (테스트)",
    "youtuber_count": 3,
    "total_processed": 42,
    "SUCCESS": 28,
    "NEEDS_REVIEW": 7,
    "NO_SUBTITLES": 5,
    "AI_ERROR": 0,
    "SKIP": 2,
    "blocked": 0,
    "failed": 0,
})
