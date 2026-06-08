"""3분봉 이평선 '수렴(스퀴즈) → 확산(돌파)' 판정.

입력: 종가 리스트(오래된→최신 순), 3분봉.
판정 기준(설명):
  - 이평선 5·10·20·60·120 계산
  - band_width(t) = (이평선 최고 - 이평선 최저) / 종가   ← 이평선들이 얼마나 벌어져 있나
  - "모임(수렴)" : 최근 구간에서 band_width 가 SQUEEZE_THRESHOLD 이하로 좁혀졌던 적이 있음
  - "퍼짐(확산)" : 지금 band_width 가 (직전보다 커지면서) 수렴최저폭의 EXPANSION_RATIO 배
                  이상으로 터지고, 이평선이 단기 정배열이며, 종가가 직전보다 상승
이 둘이 동시 충족되는 순간을 '신호'로 본다.
"""
from config import (MA_PERIODS, SQUEEZE_THRESHOLD, EXPANSION_RATIO,
                    DAILY_TREND_MA, LOOKBACK, MIN_BAND_FLOOR, EXPANSION_DISPLAY_CAP)


def _expansion_x_disp(width_now, recent_min):
    """확산배수 표시값 — 수렴이 거의 0일 때 999같은 폭주 방지(분모 클리핑+상한)."""
    return round(min(width_now / max(recent_min, MIN_BAND_FLOOR), EXPANSION_DISPLAY_CAP), 1)


def daily_uptrend(daily_closes):
    """일봉 상승추세 필터: 최근 종가가 일봉 N일 이평 위 + 그 이평이 우상향.
    데이터 부족하면 False(보수적으로 제외)."""
    n = len(daily_closes)
    if n < DAILY_TREND_MA + 5:
        return False
    ma_now = sum(daily_closes[-DAILY_TREND_MA:]) / DAILY_TREND_MA
    ma_prev = sum(daily_closes[-DAILY_TREND_MA - 5:-5]) / DAILY_TREND_MA
    return daily_closes[-1] > ma_now and ma_now >= ma_prev


def _sma(values, period, end_idx):
    """end_idx(포함) 기준 직전 period개 단순이동평균. 데이터 부족하면 None."""
    if end_idx + 1 < period:
        return None
    window = values[end_idx + 1 - period: end_idx + 1]
    return sum(window) / period

def _band_width(closes, idx):
    """idx 시점의 이평선 밴드폭 비율. (없으면 None)"""
    mas = [_sma(closes, p, idx) for p in MA_PERIODS]
    if any(m is None for m in mas):
        return None, None
    close = closes[idx]
    if close <= 0:
        return None, None
    width = (max(mas) - min(mas)) / close
    return width, mas

def squeeze_present(closes, lookback=LOOKBACK):
    """하이브리드 게이트: 이 봉(보통 3분봉)에서 최근 lookback 구간에
    수렴(밴드폭 <= SQUEEZE_THRESHOLD)이 있었는지. 묵직한 베이스 확인용."""
    n = len(closes)
    if n < max(MA_PERIODS) + lookback + 1:
        return False
    now = n - 1
    widths = [w for w in (_band_width(closes, i)[0]
                          for i in range(now - lookback, now)) if w is not None]
    return bool(widths) and min(widths) <= SQUEEZE_THRESHOLD


def detect(closes, lookback=LOOKBACK):
    """신호면 dict 반환, 아니면 None.
    lookback: '최근 수렴'을 찾을 직전 봉 수(120MA가 느려서 돌파가 완성될 즈음에도
              수렴이 잡히도록 넉넉히 본다).
    """
    n = len(closes)
    need = max(MA_PERIODS) + lookback + 1
    if n < need:
        return None  # 데이터 부족

    now = n - 1
    width_now, mas_now = _band_width(closes, now)
    width_prev, _ = _band_width(closes, now - 1)
    if width_now is None or width_prev is None:
        return None

    # 1) 최근 lookback 구간에 수렴(스퀴즈) 있었나 — 이평선들이 다닥다닥 모였던 적
    recent_min = min(
        w for w in (_band_width(closes, i)[0] for i in range(now - lookback, now))
        if w is not None
    )
    squeezed = recent_min <= SQUEEZE_THRESHOLD

    # 2) 지금 막 벌어지는 중(확산) — 수렴최저폭(recent_min)의 EXPANSION_RATIO 배 이상으로 폭이 터짐
    #    (절대 하한 SQUEEZE_THRESHOLD도 같이 둬서, 수렴이 극도로 좁았을 때 미세확산이 통과하는 것 방지)
    expanding = (width_now > width_prev) and \
                (width_now >= max(SQUEEZE_THRESHOLD, recent_min * EXPANSION_RATIO))

    # 3) 상승 방향 돌파:
    #    - 단기 정배열 5>10>20  (돌파 초기에 먼저 형성됨. 60·120 완성은 기다리지 않음)
    #    - 단기선이 장기선 위로 (5MA > 120MA) = 베이스 돌파
    #    - 종가가 상승 + 20이평 위
    short_aligned = mas_now[0] > mas_now[1] > mas_now[2]
    above_base = mas_now[0] > mas_now[-1]
    price_up = closes[now] > closes[now - 1] and closes[now] > mas_now[2]

    if squeezed and expanding and short_aligned and above_base and price_up:
        return {
            "band_width_now": round(width_now, 5),
            "recent_min_width": round(recent_min, 5),
            "expansion_x": _expansion_x_disp(width_now, recent_min),
            "ma": {p: round(m, 1) for p, m in zip(MA_PERIODS, mas_now)},
            "close": closes[now],
        }
    return None


def detect_box_breakout(bars, lookback=30, breakout_buf=0.001,
                        vol_mult_req=1.5, box_min=0.03, box_max=0.10):
    """일봉 박스권 상단 돌파 — 'bars'는 fetch_daily_bars 결과(오래된→최신, OHLCV dict).

    조건:
    - 직전 lookback 봉의 박스(고가max/저가min)에서 박스 폭이 3~20% 범위
    - 오늘 종가 > 박스상단×(1+buf), 어제 종가는 아직 그 위 아니었음(=오늘 막 돌파)
    - 오늘 거래량 ≥ 박스기간 평균거래량 × vol_mult_req
    - 손절선 = 박스 하단
    """
    if len(bars) < lookback + 2:
        return None
    box = bars[-lookback - 1:-1]            # 현재봉 제외 직전 lookback개
    cur, prev = bars[-1], bars[-2]
    box_high = max(b["high"] for b in box)
    box_low  = min(b["low"] for b in box)
    if box_low <= 0:
        return None
    box_width = (box_high - box_low) / box_low
    if not (box_min <= box_width <= box_max):
        return None
    threshold = box_high * (1 + breakout_buf)
    if not (cur["close"] > threshold and prev["close"] <= threshold):
        return None
    avg_vol = sum(b["volume"] for b in box) / max(1, len(box))
    vol_mult = cur["volume"] / avg_vol if avg_vol > 0 else 0
    if vol_mult < vol_mult_req:
        return None
    return {
        "kind": "BOX_BREAKOUT",
        "close": cur["close"],
        "box_high": box_high,
        "box_low": box_low,
        "box_width_pct": round(box_width * 100, 2),
        "stop_loss": box_low,
        "risk_pct": round((box_low - cur["close"]) / cur["close"] * 100, 2),
        "vol_mult": round(vol_mult, 2),
        "lookback_days": lookback,
    }


def detect_trendline_breakout(bars, lookback=40, swing_k=2,
                              vol_mult_req=1.5, min_slope_pct=-0.05):
    """일봉 하락추세선 돌파 — 'lower highs' 두 점을 잇는 선을 오늘 종가가 뚫음.

    swing_k: swing high 정의 — 좌우 swing_k봉보다 모두 높은 봉.
    min_slope_pct: 라인이 너무 가파르게 떨어지면 의미 약함(하루당 -5% 미만이어야).
    """
    if len(bars) < lookback + 5:
        return None
    rng = bars[-lookback - 1:-1]            # 현재봉 제외
    cur = bars[-1]
    # swing highs 찾기 (좌우 swing_k 모두보다 높음)
    swings = []
    for i in range(swing_k, len(rng) - swing_k):
        hi = rng[i]["high"]
        if all(hi > rng[i - k]["high"] for k in range(1, swing_k + 1)) and \
           all(hi > rng[i + k]["high"] for k in range(1, swing_k + 1)):
            swings.append((i, hi))
    if len(swings) < 2:
        return None
    # 마지막 swing high 와, 그것보다 더 높은 가장 가까운 이전 swing high
    last_i, last_h = swings[-1]
    prior = None
    for s in reversed(swings[:-1]):
        if s[1] > last_h:
            prior = s
            break
    if prior is None:
        return None
    prior_i, prior_h = prior
    if last_i == prior_i:
        return None
    slope = (last_h - prior_h) / (last_i - prior_i)   # 음수여야 하락추세
    if slope >= 0:
        return None
    intercept = prior_h - slope * prior_i
    # 너무 가파른 라인 제외
    if slope / max(cur["close"], 1) < min_slope_pct:
        return None
    # 현재봉 위치(= len(rng))에서의 라인값
    cur_idx = len(rng)
    line_now = intercept + slope * cur_idx
    line_prev = intercept + slope * (cur_idx - 1)
    prev = bars[-2]
    if not (cur["close"] > line_now and prev["close"] <= line_prev):
        return None
    # 거래량
    avg_vol = sum(b["volume"] for b in rng[-20:]) / 20
    vol_mult = cur["volume"] / avg_vol if avg_vol > 0 else 0
    if vol_mult < vol_mult_req:
        return None
    # 손절선 = 추세선값 3% 아래 (구조적 손절: 라인 도로 깨지면 잘못된 돌파)
    # 기존 "10봉 swing low"는 일봉에선 너무 멀어 비실용적이라 폐기.
    stop = round(line_now * 0.97)
    return {
        "kind": "TRENDLINE_BREAKOUT",
        "close": cur["close"],
        "line_value_today": round(line_now, 2),
        "slope_per_day": round(slope, 2),
        "prior_high": prior_h,
        "last_high": last_h,
        "stop_loss": stop,
        "risk_pct": round((stop - cur["close"]) / cur["close"] * 100, 2),
        "vol_mult": round(vol_mult, 2),
        "swings_count": len(swings),
    }


def detect_resistance_plus4(bars, lookback=60, swing_k=2,
                            min_pct_above=0.04, vol_mult_req=1.5):
    """저항선 + 4% 돌파(종가베팅 후보).

    영상 '저항선에서 4% 이상 멀어지면 급등' 패턴 (2026-06-08 사장님 요청).
    - lookback일 내 swing high 들 중 '의미 있는 저항선' = 최근 가장 가까운 swing high
      (단, 현재 종가보다 낮은 것이어야 — 저항을 '뚫고 위로 올라간' 상태가 핵심)
    - 종가 ≥ 저항선 × (1 + min_pct_above)  →  4% 이상 멀어짐
    - 거래량 ≥ 직전 20일 평균 × vol_mult_req
    - 어제 종가는 저항선을 4% 이상 못 떨어트림 (오늘 처음으로 4% 돌파)
    """
    if len(bars) < lookback + 5:
        return None
    rng = bars[-lookback - 1:-1]
    cur = bars[-1]
    prev = bars[-2]
    # swing highs
    swings = []
    for i in range(swing_k, len(rng) - swing_k):
        hi = rng[i]["high"]
        if all(hi > rng[i - k]["high"] for k in range(1, swing_k + 1)) and \
           all(hi > rng[i + k]["high"] for k in range(1, swing_k + 1)):
            swings.append((i, hi))
    if not swings:
        return None
    # 현재 종가보다 낮으면서 가장 가까운(시간상 최근) swing high = 저항선
    resistance = None
    for i, hi in reversed(swings):
        if hi < cur["close"]:
            resistance = hi
            break
    if resistance is None or resistance <= 0:
        return None
    pct_above = (cur["close"] - resistance) / resistance
    if pct_above < min_pct_above:
        return None
    # 어제까지는 아직 4% 멀어지지 않았어야(=오늘 막 신호 발생)
    prev_pct = (prev["close"] - resistance) / resistance
    if prev_pct >= min_pct_above:
        return None
    # 거래량
    avg_vol = sum(b["volume"] for b in rng[-20:]) / 20
    vol_mult = cur["volume"] / avg_vol if avg_vol > 0 else 0
    if vol_mult < vol_mult_req:
        return None
    # 손절선 = 저항선 (저항선이 깨지면 가짜 돌파)
    stop = round(resistance)
    return {
        "kind": "RESIST_PLUS4",
        "close": cur["close"],
        "resistance": round(resistance, 2),
        "pct_above_resist": round(pct_above * 100, 2),
        "stop_loss": stop,
        "risk_pct": round((stop - cur["close"]) / cur["close"] * 100, 2),
        "vol_mult": round(vol_mult, 2),
        "lookback_days": lookback,
    }


def explain(closes, lookback=LOOKBACK):
    """detect()의 모든 중간값·조건 통과여부를 dict로 반환(진단용).
    신호가 떴든 안 떴든 '왜 그런지' 숫자로 보여준다."""
    n = len(closes)
    need = max(MA_PERIODS) + lookback + 1
    if n < need:
        return {"error": f"데이터 부족: {n}봉 (필요 {need}봉)"}

    now = n - 1
    width_now, mas_now = _band_width(closes, now)
    width_prev, _ = _band_width(closes, now - 1)
    if width_now is None or width_prev is None:
        return {"error": "이평 계산 불가(데이터 부족)"}

    recent_min = min(
        w for w in (_band_width(closes, i)[0] for i in range(now - lookback, now))
        if w is not None
    )
    squeezed = recent_min <= SQUEEZE_THRESHOLD
    expanding = (width_now > width_prev) and \
                (width_now >= max(SQUEEZE_THRESHOLD, recent_min * EXPANSION_RATIO))
    short_aligned = mas_now[0] > mas_now[1] > mas_now[2]
    above_base = mas_now[0] > mas_now[-1]
    price_up = closes[now] > closes[now - 1] and closes[now] > mas_now[2]
    signal = squeezed and expanding and short_aligned and above_base and price_up

    return {
        "close": closes[now],
        "prev_close": closes[now - 1],
        "ma": {p: round(m, 2) for p, m in zip(MA_PERIODS, mas_now)},
        "recent_min_width": round(recent_min, 5),
        "width_prev": round(width_prev, 5),
        "width_now": round(width_now, 5),
        "expansion_x_vs_min": _expansion_x_disp(width_now, recent_min),
        "thresholds": {"SQUEEZE": SQUEEZE_THRESHOLD,
                       "EXPANSION": EXPANSION_RATIO,
                       "expand_floor(필요width)": round(max(SQUEEZE_THRESHOLD, recent_min * EXPANSION_RATIO), 5)},
        "checks": {
            "squeezed(수렴有)": squeezed,
            "expanding(확산中)": expanding,
            "short_aligned(5>10>20)": short_aligned,
            "above_base(5>120)": above_base,
            "price_up(상승+20위)": price_up,
        },
        "SIGNAL": signal,
    }
