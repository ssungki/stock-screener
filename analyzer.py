"""3분봉 이평선 '수렴(스퀴즈) → 확산(돌파)' 판정.

입력: 종가 리스트(오래된→최신 순), 3분봉.
판정 기준(설명):
  - 이평선 5·10·20·60·120 계산
  - band_width(t) = (이평선 최고 - 이평선 최저) / 종가   ← 이평선들이 얼마나 벌어져 있나
  - "모임(수렴)" : 최근 구간에서 band_width 가 SQUEEZE_THRESHOLD 이하로 좁혀졌던 적이 있음
  - "퍼짐(확산)" : 지금 band_width 가 직전보다 EXPANSION_RATIO 배 이상 커지고,
                  이평선이 정배열(5>10>20>60>120)이며, 종가가 직전보다 상승
이 둘이 동시 충족되는 순간을 '신호'로 본다.
"""
from config import MA_PERIODS, SQUEEZE_THRESHOLD, EXPANSION_RATIO

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

def detect(closes, lookback=10):
    """신호면 dict 반환, 아니면 None.
    lookback: '최근 수렴'을 찾을 직전 봉 수.
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

    # 1) 최근 lookback 구간에 수렴(스퀴즈) 있었나
    recent_min = min(
        w for w in (_band_width(closes, i)[0] for i in range(now - lookback, now))
        if w is not None
    )
    squeezed = recent_min <= SQUEEZE_THRESHOLD

    # 2) 지금 확산 전환 + 정배열 + 상승
    #    - 현재 밴드폭이 직전보다 커지는 중(벌어지는 방향)이고
    #    - 수렴 임계치의 EXPANSION_RATIO 배 이상으로 벌어졌으면 '확산'으로 본다
    #    (직전 1봉 비교만 하면 점진적 확산을 놓쳐서, 수렴 구간 탈출 여부로 판정)
    expanding = (width_now > width_prev) and (width_now >= SQUEEZE_THRESHOLD * EXPANSION_RATIO)
    aligned = all(mas_now[i] > mas_now[i + 1] for i in range(len(mas_now) - 1))  # 정배열
    price_up = closes[now] > closes[now - 1]

    if squeezed and expanding and aligned and price_up:
        return {
            "band_width_now": round(width_now, 5),
            "band_width_prev": round(width_prev, 5),
            "recent_min_width": round(recent_min, 5),
            "expansion_x": round(width_now / width_prev, 2),
            "ma": {p: round(m, 1) for p, m in zip(MA_PERIODS, mas_now)},
            "close": closes[now],
        }
    return None
