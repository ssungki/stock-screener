"""오케스트레이션:
키움 실시간 조건검색으로 1차 후보 종목을 받고,
각 종목의 3분봉을 분석해 '수렴→확산' 신호면 디코·카톡 알림.

실행: python3 main.py
"""
import time
import threading
import config
import kiwoom
import analyzer
import notifier

# 종목별 마지막 알림 시각(쿨다운)
_last_alert = {}

def _cooldown_ok(code):
    now = time.time()
    last = _last_alert.get(code, 0)
    if now - last >= config.ALERT_COOLDOWN_MIN * 60:
        _last_alert[code] = now
        return True
    return False

def handle_codes(token, codes):
    """조건검색 편입 종목들 → 3분봉 정밀 판정."""
    for code in codes:
        if not _cooldown_ok(code):
            continue
        closes = kiwoom.fetch_3min_closes(token, code)
        sig = analyzer.detect(closes)
        if sig:
            msg = (
                f"📈 [수렴→확산 포착] {code}\n"
                f"종가 {sig['close']:,} / 확산 {sig['expansion_x']}배\n"
                f"이평 {sig['ma']}"
            )
            notifier.notify(msg)
        else:
            # 신호 아님 → 쿨다운 해제(다음 편입 때 다시 검사)
            _last_alert.pop(code, None)

def main():
    if not (config.APPKEY and config.SECRETKEY):
        raise SystemExit("KIWOOM_APPKEY/SECRETKEY 가 비어있습니다. .env 를 채우세요.")

    print("[main] 토큰 발급...", flush=True)
    token = kiwoom.get_access_token()
    print("[main] 토큰 OK", flush=True)
    notifier.notify("🟢 주식 검색기 시작 — 실시간 조건검색 대기 중")

    stream = kiwoom.ConditionStream(
        token=token,
        condition_name=config.CONDITION_NAME,
        on_codes=lambda codes: handle_codes(token, codes),
    )
    try:
        stream.run_forever()
    except KeyboardInterrupt:
        stream.stop()
        notifier.notify("🔴 주식 검색기 종료")

if __name__ == "__main__":
    main()
