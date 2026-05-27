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
    # 후보 풀 = 급등주 교집합(전일대비등락률상위 ∩ 거래량급증 ∩ 종가≥MIN_PRICE)
    stocks = kiwoom.fetch_surge_universe(token)
    print(f"[scan] 급등주 후보 {len(stocks)}종목 점검", flush=True)
    hits = 0
    for code, name in stocks:
        try:
            if not _daily_ok(token, code):
                continue
            # 1) 돌파 트리거: 트리거 봉(1분봉)에서 수렴→확산 포착(빠름)
            c_trig = kiwoom.fetch_intraday_closes(token, code, tic=config.TRIGGER_TIC)
            time.sleep(config.REQ_DELAY_SEC)
            sig = analyzer.detect(c_trig)
            if not sig:
                continue
            # 2) 베이스 게이트: 수렴 봉(3분봉)에 묵직한 수렴이 있었는지 확인
            c_sq = kiwoom.fetch_intraday_closes(token, code, tic=config.SQUEEZE_TIC)
            time.sleep(config.REQ_DELAY_SEC)
            if not analyzer.squeeze_present(c_sq):
                continue
            if _cooldown_ok(code):
                _last_alert[code] = time.time()
                hits += 1
                now_kst = datetime.now(KST).strftime("%H:%M:%S")
                notifier.notify(
                    f"📈 [수렴→확산] {name} ({code})\n"
                    f"종가 {int(sig['close']):,} / 확산 {sig['expansion_x']}배\n"
                    f"발송 {now_kst} (한국시간)"
                )
        except Exception as e:
            print(f"[scan] {code} 처리 오류: {e}", flush=True)
    print(f"[scan] 완료 — 신호 {hits}건", flush=True)


def replay(token, code):
    """오늘 분봉을 처음부터 훑으며 하이브리드 신호가 언제 떴을지 재현(검증용)."""
    trig = kiwoom.fetch_intraday_bars(token, code, tic=config.TRIGGER_TIC, count=400)
    sq = kiwoom.fetch_intraday_bars(token, code, tic=config.SQUEEZE_TIC, count=200)
    up = analyzer.daily_uptrend(kiwoom.fetch_daily_closes(token, code))
    print(f"[replay] {code} — 트리거{config.TRIGGER_TIC}분봉 {len(trig)}개 / "
          f"수렴{config.SQUEEZE_TIC}분봉 {len(sq)}개 / 일봉상승추세={up}", flush=True)
    if not trig:
        print("[replay] 분봉 데이터 없음", flush=True)
        return
    trig_closes = [c for _, c in trig]
    need = max(analyzer.MA_PERIODS) + analyzer.LOOKBACK + 1
    fired = []
    for i in range(need, len(trig)):
        sig = analyzer.detect(trig_closes[:i + 1])
        if not sig:
            continue
        t = trig[i][0]                                  # 그 봉의 체결시간
        sq_sub = [c for (tt, c) in sq if tt and tt <= t] or [c for _, c in sq]
        gate = analyzer.squeeze_present(sq_sub)
        fired.append((t, gate))
        mark = "✅최종신호" if gate else "⚠️트리거만(베이스 미충족)"
        print(f"  {t[-6:]}  {mark}  종가 {int(sig['close']):,} 확산 {sig['expansion_x']}배", flush=True)
    real = [f for f in fired if f[1]]
    print(f"[replay] 트리거 {len(fired)}회 / 최종신호(베이스 통과) {len(real)}회"
          + (f" / 첫 신호 {real[0][0][-6:]}" if real else ""), flush=True)


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
    if arg == "why":
        # python main.py why <종목코드>  — 그 종목이 왜 신호인지/아닌지 숫자로 분석
        code = sys.argv[2] if len(sys.argv) > 2 else ""
        if not code:
            print("사용법: python main.py why <종목코드>  (예: why 064290)", flush=True)
            return
        import json as _json
        daily = kiwoom.fetch_daily_closes(token, code)
        closes = kiwoom.fetch_intraday_closes(token, code)
        print(f"[why] {code} — 일봉 {len(daily)}개, {config.TICK_MIN}분봉 {len(closes)}개", flush=True)
        print(f"[why] 일봉 상승추세(daily_uptrend)? {analyzer.daily_uptrend(daily)}", flush=True)
        info = analyzer.explain(closes)
        print(f"[why] {config.TICK_MIN}분봉 판정 상세:\n" + _json.dumps(info, ensure_ascii=False, indent=2), flush=True)
        return
    if arg == "replay":
        # python main.py replay <종목코드>  — 오늘 분봉 재현해 신호 시각 검증
        code = sys.argv[2] if len(sys.argv) > 2 else ""
        if not code:
            print("사용법: python main.py replay <종목코드>  (예: replay 064400)", flush=True)
            return
        replay(token, code)
        return

    notifier.notify(
        f"🟢 주식 검색기 시작 — 급등주 풀(등락률∩거래량급증) / "
        f"트리거 {config.TRIGGER_TIC}분봉·수렴 {config.SQUEEZE_TIC}분봉 / "
        f"{config.POLL_INTERVAL_SEC}초 주기"
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
