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
