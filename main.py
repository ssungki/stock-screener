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
import storage

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
            # 장 초반 변동성 구간(09:00~09:15 등) 알람 보류 — 가짜 돌파 다발 구간
            now_dt = datetime.now(KST)
            hm_now = now_dt.hour * 60 + now_dt.minute
            if hm_now < config.MARKET_OPEN_HM + config.NO_ALERT_FIRST_MIN:
                continue
            if _cooldown_ok(code):
                _last_alert[code] = time.time()
                hits += 1
                now_kst = now_dt.strftime("%H:%M:%S")
                notifier.notify(
                    f"📈 [수렴→확산] {name} ({code})\n"
                    f"종가 {int(sig['close']):,} / 확산 {sig['expansion_x']}배\n"
                    f"발송 {now_kst} (한국시간)"
                )
                # SQLite 영구 로깅(VM 죽어도 보존)
                storage.log_alert(
                    date_kst=now_dt.strftime("%Y%m%d"),
                    time_kst=now_dt.strftime("%H%M%S"),
                    code=code, name=name,
                    buy_price=sig["close"],
                    expansion_x=sig["expansion_x"],
                    recent_min_w=sig["recent_min_width"],
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


def scan_daily_breakouts(token, top_n=300):
    """거래대금 상위 N에서 일봉 박스권/하락추세선 돌파를 스캔. 알람 후보 리스트 반환.
    매일 장 마감 후 1회 호출용 — 분당 폴링 X."""
    stocks = kiwoom.fetch_top_value_codes(token, top_n)
    print(f"[breakout] 일봉 돌파 스캔 — 후보 {len(stocks)}종목", flush=True)
    hits = []
    for code, name in stocks:
        try:
            bars = kiwoom.fetch_daily_bars(token, code, count=80)
            time.sleep(config.REQ_DELAY_SEC)
            if not bars or len(bars) < 35:
                continue
            box = analyzer.detect_box_breakout(bars)
            trend = analyzer.detect_trendline_breakout(bars)
            if box:
                hits.append({"code": code, "name": name, "kind": "BOX", "sig": box})
            if trend:
                hits.append({"code": code, "name": name, "kind": "TREND", "sig": trend})
        except Exception as e:
            print(f"[breakout] {code} 처리 오류: {e}", flush=True)
    print(f"[breakout] 완료 — 박스 "
          f"{sum(1 for h in hits if h['kind']=='BOX')}건 / "
          f"추세선 {sum(1 for h in hits if h['kind']=='TREND')}건", flush=True)
    return hits


def post_breakout_scan(token):
    """일봉 돌파 스캔 → 각 종목 ntfy/디스코드 + 헤더 요약."""
    hits = scan_daily_breakouts(token)
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    if not hits:
        notifier.send_discord(f"📅 **{today_str} 일봉 돌파 스캔** — 오늘 돌파 종목 없음")
        return
    notifier.send_discord(f"📅 **{today_str} 일봉 돌파 스캔** — {len(hits)}건 ↓")
    for h in hits:
        s = h["sig"]
        if h["kind"] == "BOX":
            text = (f"🟦 [일봉 박스돌파] {h['name']} ({h['code']})\n"
                    f"종가 {int(s['close']):,} / 박스 "
                    f"{int(s['box_low']):,}~{int(s['box_high']):,} (폭 {s['box_width_pct']}%)\n"
                    f"손절가 {int(s['stop_loss']):,} ({s['risk_pct']}%) / "
                    f"거래량 {s['vol_mult']}배 / {s['lookback_days']}일 박스")
        else:
            text = (f"🔻 [일봉 추세선돌파] {h['name']} ({h['code']})\n"
                    f"종가 {int(s['close']):,} / 추세선값 "
                    f"{int(s['line_value_today']):,} 돌파\n"
                    f"손절가 {int(s['stop_loss']):,} ({s['risk_pct']}%) / "
                    f"거래량 {s['vol_mult']}배 / 직전 고점 {int(s['prior_high']):,}→{int(s['last_high']):,}")
        notifier.notify(text)


def post_weekly_report():
    """이번 주(월~금) SQLite에 쌓인 알람·결과를 부분집단별로 집계해 디스코드 포스트.
    백테스트 outcomes를 미리 SQLite에 저장해뒀기 때문에 API 재호출 불필요(빠름)."""
    if not config.DISCORD_WEBHOOK_URL:
        print("[weekly] DISCORD_WEBHOOK_URL 없음 — 포스트 안 함", flush=True)
        return
    today = datetime.now(KST)
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).strftime("%Y%m%d") for i in range(5)]
    rows = []
    for d in dates:
        rows.extend(storage.fetch_alerts(d))
    rows = [r for r in rows if r.get("close_pct") is not None]
    header = f"📅 **주간 통계 {dates[0]}~{dates[-1]}**"
    if not rows:
        notifier.send_discord(f"{header}\n이번 주 분석 가능 신호 0건.")
        print(f"{header}\n신호 없음", flush=True); return
    n = len(rows)
    wins = sum(1 for r in rows if (r["close_pct"] or 0) > 0)
    avg_close = sum(r["close_pct"] for r in rows) / n
    valid_rule = [r["rule_pct"] for r in rows if r.get("rule_pct") is not None]
    avg_rule = sum(valid_rule) / len(valid_rule) if valid_rule else 0.0
    take_cnt = sum(1 for r in rows if r.get("rule_kind") == "TAKE")
    stop_cnt = sum(1 for r in rows if r.get("rule_kind") == "STOP")
    hold_cnt = n - take_cnt - stop_cnt
    def _hour_bucket(t):
        try: h = int((t or "")[:2])
        except: return "?"
        return f"{h:02d}시대"
    def _exp_bucket(x):
        if x is None: return "?"
        if x < 3: return "1.<3배"
        if x < 5: return "2.3~5배"
        if x < 10: return "3.5~10배"
        if x < 20: return "4.10~20배"
        return "5.>20배"
    def _agg(get_key):
        d = {}
        for r in rows:
            d.setdefault(get_key(r), []).append(r["close_pct"])
        return sorted(d.items())
    def _fmt_group(label, groups):
        out = [f"\n[{label}]"]
        for k, vs in groups:
            w = sum(1 for v in vs if v > 0)
            out.append(f"  {k:<12} {len(vs):>3}건  승 {w}/{len(vs)} = {w/len(vs)*100:>4.0f}%  평균 {sum(vs)/len(vs)*100:>+6.2f}%")
        return "\n".join(out)
    body = (
        f"신호 {n}건  /  승 {wins}/{n} = {wins/n*100:.1f}%\n"
        f"종일보유 평균 {avg_close*100:+.2f}%  /  +5%-3%룰 평균 {avg_rule*100:+.2f}% "
        f"(익절 {take_cnt} / 손절 {stop_cnt} / 미발동 {hold_cnt})"
        + _fmt_group("시간대별", _agg(lambda r: _hour_bucket(r["time_kst"])))
        + _fmt_group("확산배수별", _agg(lambda r: _exp_bucket(r.get("expansion_x"))))
    )
    msg = f"{header}\n```\n{body}\n```"
    if len(msg) > 1950: msg = msg[:1950] + "\n... (잘림)```"
    notifier.send_discord(msg)
    print(header + "\n" + body, flush=True)


def post_daily_report(token, capital=1_000_000):
    """backtest_today 출력을 통째로 캡처해 Discord 웹훅으로 전송."""
    import io
    import contextlib
    if not config.DISCORD_WEBHOOK_URL:
        print("[report] DISCORD_WEBHOOK_URL 없음 — 포스트 안 함", flush=True)
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        backtest_today(token, capital=capital)
    body = buf.getvalue().rstrip()
    # Discord 메시지 한도 2000자. 코드블록 래퍼 길이 감안 ~1850자로 자름.
    if len(body) > 1850:
        body = body[:1850] + "\n... (잘림)"
    header = f"📊 **{datetime.now(KST).strftime('%Y-%m-%d')} 일일 리포트**"
    notifier.send_discord(f"{header}\n```\n{body}\n```")
    # 콘솔에도 그대로 출력해 journal에 남기기
    print(header, flush=True)
    print(body, flush=True)


def backtest_today(token, capital=1_000_000):
    """오늘 떴던 알람을 journalctl에서 긁어, 각 알람 시점에 capital원씩 매수했다고
    가정하고 현재가로 손익을 계산. 알람의 종가/발송시각은 알림 본문에서 파싱."""
    import subprocess
    import re
    try:
        raw = subprocess.check_output(
            ["journalctl", "-u", "stock-screener", "--since", "today", "--no-pager"],
            text=True, errors="replace")
    except Exception as e:
        print(f"[backtest] journalctl 실패: {e}", flush=True)
        return
    lines = raw.splitlines()
    re_head = re.compile(r"\[알림\] 📈 \[수렴→확산\] (.+?) \((\d{6})\)")
    re_buy  = re.compile(r"종가\s+([\d,]+)\s*/\s*확산\s+([\d.]+)\s*배")
    re_send = re.compile(r"발송\s+([\d:]+)\s*\(한국시간\)")
    alerts = []
    for i, ln in enumerate(lines):
        m = re_head.search(ln)
        if not m:
            continue
        name, code = m.group(1).strip(), m.group(2)
        price = exp = send = None
        for j in range(i + 1, min(i + 6, len(lines))):
            if (mp := re_buy.search(lines[j])):
                price = int(mp.group(1).replace(",", ""))
                exp = float(mp.group(2))
            if (ms := re_send.search(lines[j])):
                send = ms.group(1)
            if price and send:
                break
        if price:
            alerts.append({"send": send or "?", "name": name, "code": code,
                           "buy": price, "exp": exp})
    if not alerts:
        print("[backtest] 오늘 신호 알람 없음(시작 알람만 있거나 아예 없음)", flush=True)
        return
    today = datetime.now(KST).strftime("%Y%m%d")
    TAKE_PROFIT = 0.05    # +5% 익절
    STOP_LOSS   = -0.03   # -3% 손절
    print(f"[backtest] 오늘 신호 {len(alerts)}건 — 각 {capital:,}원 매수 / 익절+5% 손절-3% 룰 시뮬\n", flush=True)
    print(f"{'시각':<10}{'종목':<10}{'코드':<7}{'매수':>8}{'현재':>8}{'현재%':>8}{'MFE%':>8}{'MAE%':>8}  룰결과 (시각 / 최고시각·최저시각)")
    print("-" * 110)
    total_now_pnl = 0
    total_rule_pnl = 0
    total_capital = 0
    cnt_take = cnt_stop = 0
    for a in alerts:
        bars = kiwoom.fetch_intraday_bars(token, a["code"], tic=1, count=400)
        alert_ts = today + (a["send"] or "").replace(":", "")
        post = [(t, c) for (t, c) in bars if t and t >= alert_ts]
        time.sleep(config.REQ_DELAY_SEC)
        if not post:
            print(f"{a['send']:<10}{a['name']:<10}{a['code']:<7}{a['buy']:>8,}{'?':>8}{'?':>8}{'?':>8}{'?':>8}  (데이터없음)")
            continue
        cur = int(post[-1][1])
        cur_ret = (cur - a["buy"]) / a["buy"]
        # MFE/MAE = 알람 후 최고/최저 도달 종가
        max_t, max_c = max(post, key=lambda x: x[1])
        min_t, min_c = min(post, key=lambda x: x[1])
        mfe = (max_c - a["buy"]) / a["buy"]
        mae = (min_c - a["buy"]) / a["buy"]
        # 룰 시뮬: 시간순으로 +5%·-3% 중 먼저 닿는 쪽이 청산
        rule_kind, rule_t, rule_ret = "HOLD", post[-1][0], cur_ret
        for t, c in post:
            pct = (c - a["buy"]) / a["buy"]
            if pct <= STOP_LOSS:
                rule_kind, rule_t, rule_ret = "STOP", t, STOP_LOSS; break
            if pct >= TAKE_PROFIT:
                rule_kind, rule_t, rule_ret = "TAKE", t, TAKE_PROFIT; break
        shares = capital // a["buy"]
        invested = shares * a["buy"]
        now_pnl = shares * (cur - a["buy"])
        rule_pnl = int(invested * rule_ret)
        total_now_pnl += now_pnl
        total_rule_pnl += rule_pnl
        total_capital += invested
        if rule_kind == "TAKE": cnt_take += 1
        elif rule_kind == "STOP": cnt_stop += 1
        # SQLite outcomes 영속화 — 주간 통계 등 사후 분석용
        storage.update_outcomes(
            date_kst=today, time_kst=a["send"].replace(":", ""), code=a["code"],
            mfe_pct=mfe, mae_pct=mae, mfe_time=max_t, mae_time=min_t,
            close_pct=cur_ret, rule_kind=rule_kind, rule_pct=rule_ret, rule_time=rule_t,
        )
        tag = {"TAKE": "✅익절+5", "STOP": "❌손절-3", "HOLD": "⏸️종일보유"}[rule_kind]
        rt = rule_t[-6:-2] if rule_t and len(rule_t) >= 6 else "?"
        mt = max_t[-6:-2] if max_t and len(max_t) >= 6 else "?"
        nt = min_t[-6:-2] if min_t and len(min_t) >= 6 else "?"
        print(f"{a['send']:<10}{a['name']:<10}{a['code']:<7}{a['buy']:>8,}{cur:>8,}"
              f"{cur_ret*100:>+7.2f}%{mfe*100:>+7.2f}%{mae*100:>+7.2f}%  "
              f"{tag}@{rt} (최고{mt}/최저{nt})")
    print("-" * 110)
    if total_capital:
        print(f"\n[종일 보유]   손익 {total_now_pnl:+,}원  ({total_now_pnl/total_capital*100:+.2f}%)")
        print(f"[+5%/-3% 룰] 손익 {total_rule_pnl:+,}원  ({total_rule_pnl/total_capital*100:+.2f}%)  "
              f"— 익절 {cnt_take}회 / 손절 {cnt_stop}회 / 미발동 {len(alerts) - cnt_take - cnt_stop}회")
        diff = total_rule_pnl - total_now_pnl
        print(f"\n청산룰 효과: {diff:+,}원  ({diff/total_capital*100:+.2f}%p)")


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
    if arg == "backtest_today":
        # python main.py backtest_today [원금]  — 오늘 알람마다 N원씩 샀다 가정 손익
        cap = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
        backtest_today(token, capital=cap)
        return
    if arg == "post_daily_report":
        # python main.py post_daily_report  — 디스코드 웹훅으로 오늘 백테스트 결과 자동 포스트
        post_daily_report(token, capital=1_000_000)
        return
    if arg == "post_weekly_report":
        # python main.py post_weekly_report  — 이번주(월~금) SQLite 데이터로 주간 통계 포스트
        post_weekly_report()
        return
    if arg == "post_breakout_scan":
        # python main.py post_breakout_scan  — 일봉 박스/추세선 돌파 스캔 → ntfy+디스코드
        post_breakout_scan(token)
        return
    if arg == "backfill":
        # python main.py backfill  — 오늘 journal의 알람들을 SQLite에 채워넣기(과거 알람 보존)
        import subprocess, re
        raw = subprocess.check_output(
            ["journalctl", "-u", "stock-screener", "--since", "today", "--no-pager"],
            text=True, errors="replace")
        lines = raw.splitlines()
        re_head = re.compile(r"\[알림\] 📈 \[수렴→확산\] (.+?) \((\d{6})\)")
        re_buy  = re.compile(r"종가\s+([\d,]+)\s*/\s*확산\s+([\d.]+)\s*배")
        re_send = re.compile(r"발송\s+([\d:]+)\s*\(한국시간\)")
        today_kst = datetime.now(KST).strftime("%Y%m%d")
        n = 0
        for i, ln in enumerate(lines):
            m = re_head.search(ln)
            if not m: continue
            name, code = m.group(1).strip(), m.group(2)
            price = exp = send = None
            for j in range(i + 1, min(i + 6, len(lines))):
                if (mp := re_buy.search(lines[j])):
                    price = float(mp.group(1).replace(",", ""))
                    exp = float(mp.group(2))
                if (ms := re_send.search(lines[j])):
                    send = ms.group(1)
                if price and send: break
            if price and send:
                storage.log_alert(today_kst, send.replace(":", ""),
                                  code, name, price, exp, None)
                n += 1
        print(f"[backfill] 오늘 알람 {n}건 SQLite 적재(중복은 무시)", flush=True)
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
