"""오케스트레이션 (폴링 방식 — 영웅문 조건검색 불필요).

흐름:
  거래대금 상위 N종목 수집(ka10032)
   → 각 종목 일봉으로 '상승추세' 1차 필터(analyzer.daily_uptrend)
   → 통과 종목 3분봉으로 '수렴→확산' 정밀 판정(analyzer.detect)
   → 신호면 알림(디코/카카오/ntfy), 종목별 쿨다운
장중(평일 09:00~15:30 KST)에만 스캔. POLL_INTERVAL_SEC 주기 반복.

실행:        python3 main.py
진단(1회):   python3 main.py probe   ← 실제 키움 응답 구조 확인
1회 스캔:    python3 main.py once    ← 즉시 한 바퀴(장 시간 무시)
"""
import sys
import time
from datetime import datetime, timezone, timedelta

import config
import kiwoom
import analyzer
import notifier

KST = timezone(timedelta(hours=9))

_last_alert = {}                 # code -> 마지막 알림 epoch
_daily_cache = {}                # code -> (yyyymmdd, closes)  일봉은 하루 1회만 조회
_token = {"val": None, "ts": 0}  # 토큰 + 발급시각


def _get_token():
    """6시간마다 토큰 재발급(만료 방지)."""
    if not _token["val"] or time.time() - _token["ts"] > 6 * 3600:
        _token["val"] = kiwoom.get_access_token()
        _token["ts"] = time.time()
        print("[token] 발급/갱신 OK", flush=True)
    return _token["val"]


def _cooldown_ok(code):
    now = time.time()
    if now - _last_alert.get(code, 0) >= config.ALERT_COOLDOWN_MIN * 60:
        return True
    return False


def _daily_ok(token, code):
    """일봉 상승추세 필터(하루 1회 조회 후 캐시)."""
    today = datetime.now(KST).strftime("%Y%m%d")
    cached = _daily_cache.get(code)
    if cached and cached[0] == today:
        closes = cached[1]
    else:
        closes = kiwoom.fetch_daily_closes(token, code)
        _daily_cache[code] = (today, closes)
        time.sleep(config.REQ_DELAY_SEC)
    return analyzer.daily_uptrend(closes)


def scan_once(token):
    codes = kiwoom.fetch_top_value_codes(token, config.TOP_N)
    print(f"[scan] 거래대금 상위 {len(codes)}종목 점검", flush=True)
    hits = 0
    for code in codes:
        try:
            if not _daily_ok(token, code):
                continue
            closes = kiwoom.fetch_3min_closes(token, code)
            time.sleep(config.REQ_DELAY_SEC)
            sig = analyzer.detect(closes)
            if sig and _cooldown_ok(code):
                _last_alert[code] = time.time()
                hits += 1
                notifier.notify(
                    f"📈 [수렴→확산] {code}\n"
                    f"종가 {int(sig['close']):,} / 확산 {sig['expansion_x']}배\n"
                    f"3분봉 이평 {sig['ma']}"
                )
        except Exception as e:
            print(f"[scan] {code} 처리 오류: {e}", flush=True)
    print(f"[scan] 완료 — 신호 {hits}건", flush=True)


def _market_open():
    now = datetime.now(KST)
    if now.weekday() >= 5:                     # 토(5)·일(6)
        return False
    hm = now.hour * 60 + now.minute
    return config.MARKET_OPEN_HM <= hm <= config.MARKET_CLOSE_HM


def main():
    if not (config.APPKEY and config.SECRETKEY):
        raise SystemExit("KIWOOM_APPKEY/SECRETKEY 가 비어있습니다. .env 를 채우세요.")

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    token = _get_token()

    if arg == "probe":
        kiwoom.probe(token)
        return
    if arg == "once":
        scan_once(token)
        return

    notifier.notify(
        f"🟢 주식 검색기 시작 — 거래대금 상위 {config.TOP_N}종목 / "
        f"{config.POLL_INTERVAL_SEC}초 주기 / 장중 가동"
    )
    while True:
        try:
            if _market_open():
                scan_once(_get_token())
            else:
                print(f"[idle] 장 시간 아님 ({datetime.now(KST):%H:%M})", flush=True)
        except Exception as e:
            print(f"[main] 스캔 예외: {e}", flush=True)
        time.sleep(config.POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
