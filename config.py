"""환경설정 로더. .env 파일(없으면 OS 환경변수)에서 값을 읽는다."""
import os
from pathlib import Path

def _load_env_file():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

_load_env_file()

def get(name, default=None):
    return os.environ.get(name, default)

# 키움
APPKEY        = get("KIWOOM_APPKEY", "")
SECRETKEY     = get("KIWOOM_SECRETKEY", "")
REST_BASE     = get("KIWOOM_REST_BASE", "https://api.kiwoom.com")
WS_URL        = get("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000/api/dostk/websocket")
CONDITION_NAME = get("CONDITION_NAME", "")

# 알림
DISCORD_WEBHOOK_URL = get("DISCORD_WEBHOOK_URL", "")
KAKAO_REST_API_KEY  = get("KAKAO_REST_API_KEY", "")
KAKAO_REFRESH_TOKEN = get("KAKAO_REFRESH_TOKEN", "")
# ntfy.sh — 전용 알림 푸시(PC앱/폰앱, 큰 소리·최우선 알림). 토픽명만 정하면 됨(가입 불필요).
NTFY_TOPIC = get("NTFY_TOPIC", "")
NTFY_SERVER = get("NTFY_SERVER", "https://ntfy.sh")

# 판정 파라미터
MA_PERIODS       = [int(x) for x in get("MA_PERIODS", "5,10,20,60,120").split(",")]
SQUEEZE_THRESHOLD = float(get("SQUEEZE_THRESHOLD", "0.015"))
EXPANSION_RATIO   = float(get("EXPANSION_RATIO", "1.3"))
LOOKBACK          = int(get("LOOKBACK", "20"))          # 수렴(스퀴즈) 탐색 구간(직전 봉 수)
ALERT_COOLDOWN_MIN = int(get("ALERT_COOLDOWN_MIN", "30"))
DAILY_TREND_MA   = int(get("DAILY_TREND_MA", "20"))      # 일봉 상승추세 판정 이평기간

# 폴링(거래대금 상위 스캔)
TICK_MIN          = get("TICK_MIN", "3")                 # 분봉 단위(분). 1=1분봉(단타,빠름) 3=3분봉
TOP_N             = int(get("TOP_N", "100"))             # 거래대금 상위 몇 종목 감시
POLL_INTERVAL_SEC = int(get("POLL_INTERVAL_SEC", "120")) # 스캔 주기(초)
REQ_DELAY_SEC     = float(get("REQ_DELAY_SEC", "0.3"))   # API 호출 간 간격(레이트리밋)
MRKT_TP           = get("MRKT_TP", "000")                # 000:전체 001:코스피 101:코스닥
STEX_TP           = get("STEX_TP", "1")                  # 1:KRX 2:NXT 3:통합
MARKET_OPEN_HM    = int(get("MARKET_OPEN_HM", "540"))    # 09:00 = 9*60
MARKET_CLOSE_HM   = int(get("MARKET_CLOSE_HM", "930"))   # 15:30 = 15*60+30
