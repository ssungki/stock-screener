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
MIN_BAND_FLOOR    = float(get("MIN_BAND_FLOOR", "0.003")) # 확산배수 분모 클리핑(수렴 0에 가까울 때 999 노이즈 방지)
EXPANSION_DISPLAY_CAP = float(get("EXPANSION_DISPLAY_CAP", "50")) # 표시용 확산배수 상한
ALERT_COOLDOWN_MIN = int(get("ALERT_COOLDOWN_MIN", "30"))
DAILY_TREND_MA   = int(get("DAILY_TREND_MA", "20"))      # 일봉 상승추세 판정 이평기간

# 폴링 / 하이브리드 봉
TRIGGER_TIC       = get("TRIGGER_TIC", "1")              # 돌파 트리거 봉(분). 1=1분봉(빠른 포착)
SQUEEZE_TIC       = get("SQUEEZE_TIC", "3")              # 수렴 게이트 봉(분). 3=3분봉(묵직한 베이스)
TICK_MIN          = get("TICK_MIN", TRIGGER_TIC)         # (구) 단일 봉 단위 — 기본은 트리거 봉
TOP_N             = int(get("TOP_N", "100"))             # (구) 거래대금 상위 N (universe=surge면 미사용)
POLL_INTERVAL_SEC = int(get("POLL_INTERVAL_SEC", "120")) # 스캔 주기(초)

# 급등주 후보 풀(교집합): 전일대비등락률상위 ∩ 거래량급증 ∩ 종가>=MIN_PRICE
RANK_CHANGE_TOP   = int(get("RANK_CHANGE_TOP", "200"))   # 전일대비 등락률 상위 N
RANK_VOLSPIKE_TOP = int(get("RANK_VOLSPIKE_TOP", "100")) # 거래량 급증 상위 N
MIN_PRICE         = float(get("MIN_PRICE", "1000"))      # 종가 하한(원). cur_prc 스케일은 probe로 검증
REQ_DELAY_SEC     = float(get("REQ_DELAY_SEC", "0.3"))   # API 호출 간 간격(레이트리밋)
MRKT_TP           = get("MRKT_TP", "000")                # 000:전체 001:코스피 101:코스닥
STEX_TP           = get("STEX_TP", "1")                  # 1:KRX 2:NXT 3:통합
MARKET_OPEN_HM    = int(get("MARKET_OPEN_HM", "540"))    # 09:00 = 9*60
MARKET_CLOSE_HM   = int(get("MARKET_CLOSE_HM", "930"))   # 15:30 = 15*60+30
NO_ALERT_FIRST_MIN = int(get("NO_ALERT_FIRST_MIN", "15")) # 장 초반 N분 알람 보류(변동성 구간)
