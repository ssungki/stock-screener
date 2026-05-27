"""키움 REST API 클라이언트 (폴링 방식).

- 접근토큰 발급 (POST /oauth2/token)
- 거래대금 상위 종목 (ka10032, /api/dostk/rkinfo)
- 일봉 차트 (ka10081, /api/dostk/chart)  ← 일봉 상승추세 필터용
- 분봉 차트 (ka10080, /api/dostk/chart)  ← 3분봉 수렴→확산 판정용

필드명은 키움 신형 REST 스펙 기준:
  분봉/일봉 응답 배열 = stk_min_pole_chart_qry / stk_dt_pole_chart_qry
  봉 항목 = cur_prc(현재가, +/- 부호 가능), dt(일자), cntr_tm(체결시간)
  거래대금상위 응답 배열 = trde_prica_upper, 항목 stk_cd / stk_nm / cur_prc
"""
import requests
import config

CHART_EP = f"{config.REST_BASE}/api/dostk/chart"
RANK_EP = f"{config.REST_BASE}/api/dostk/rkinfo"


# ─────────────────────────── 토큰 ───────────────────────────
def get_access_token():
    r = requests.post(
        f"{config.REST_BASE}/oauth2/token",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={
            "grant_type": "client_credentials",
            "appkey": config.APPKEY,
            "secretkey": config.SECRETKEY,
        },
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()
    if "token" not in d:
        raise RuntimeError(f"토큰 발급 실패: {d}")
    return d["token"]


def _post(endpoint, api_id, token, body, timeout=10):
    """공통 POST. (응답 dict 반환, 실패 시 예외)"""
    r = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": api_id,
        },
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def _to_num(v):
    """'+12,345' / '-1,200' / '12345' → 12345.0 (부호 무시, 절대값)."""
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").strip()
    if s in ("", "-"):
        return None
    try:
        return abs(float(s))
    except ValueError:
        return None


# ─────────────────── 거래대금 상위 (ka10032) ───────────────────
def fetch_top_value_codes(token, count=100):
    """거래대금 상위 종목코드 리스트(상위→하위). 최대 count개."""
    d = _post(RANK_EP, "ka10032", token, {
        "mrkt_tp": config.MRKT_TP,          # 000:전체 001:코스피 101:코스닥
        "mang_stk_incls": "0",              # 관리종목 미포함
        "stex_tp": config.STEX_TP,          # 1:KRX 2:NXT 3:통합
    })
    rows = d.get("trde_prica_upper") or []
    codes = []
    for row in rows:
        c = row.get("stk_cd")
        if c:
            codes.append(c.lstrip("A").strip())
        if len(codes) >= count:
            break
    return codes


# ─────────────────── 일봉 (ka10081) — 추세 필터 ───────────────────
def fetch_daily_closes(token, stk_cd, count=60):
    """일봉 종가 리스트(오래된→최신)."""
    try:
        d = _post(CHART_EP, "ka10081", token, {
            "stk_cd": stk_cd,
            "base_dt": "",                  # 빈값=오늘 기준
            "upd_stkpc_tp": "1",            # 수정주가 반영
        })
        rows = d.get("stk_dt_pole_chart_qry") or []
        closes = [c for c in (_to_num(r.get("cur_prc")) for r in rows) if c]
        closes.reverse()                    # 키움은 최신이 앞 → 오래된→최신
        return closes[-count:]
    except Exception as e:
        print(f"[daily] {stk_cd} 일봉 실패: {e}", flush=True)
        return []


# ─────────────────── 분봉 (ka10080) — 수렴/확산 판정 ───────────────────
def fetch_3min_closes(token, stk_cd, count=160):
    """3분봉 종가 리스트(오래된→최신)."""
    try:
        d = _post(CHART_EP, "ka10080", token, {
            "stk_cd": stk_cd,
            "tic_scope": "3",               # 3분
            "upd_stkpc_tp": "1",
        })
        rows = d.get("stk_min_pole_chart_qry") or []
        closes = [c for c in (_to_num(r.get("cur_prc")) for r in rows) if c]
        closes.reverse()
        return closes[-count:]
    except Exception as e:
        print(f"[min] {stk_cd} 분봉 실패: {e}", flush=True)
        return []


# ─────────────────────────── 진단(probe) ───────────────────────────
def probe(token):
    """실제 응답 구조를 눈으로 확인하는 진단. 필드명/정렬 검증용."""
    print("── 거래대금상위(ka10032) ──", flush=True)
    d = _post(RANK_EP, "ka10032", token, {
        "mrkt_tp": config.MRKT_TP, "mang_stk_incls": "0", "stex_tp": config.STEX_TP,
    })
    print("top keys:", list(d.keys()), flush=True)
    rows = d.get("trde_prica_upper") or []
    print(f"종목수: {len(rows)} / 상위5:", flush=True)
    for r in rows[:5]:
        print("  ", {k: r.get(k) for k in ("now_rank", "stk_cd", "stk_nm", "cur_prc")}, flush=True)

    if rows:
        code = (rows[0].get("stk_cd") or "").lstrip("A")
        print(f"\n── 일봉(ka10081) {code} ──", flush=True)
        dd = _post(CHART_EP, "ka10081", token, {"stk_cd": code, "base_dt": "", "upd_stkpc_tp": "1"})
        print("keys:", list(dd.keys()), flush=True)
        dr = dd.get("stk_dt_pole_chart_qry") or []
        print(f"봉수:{len(dr)} 앞3:", [{k: x.get(k) for k in ('dt', 'cur_prc')} for x in dr[:3]], flush=True)

        print(f"\n── 3분봉(ka10080) {code} ──", flush=True)
        dm = _post(CHART_EP, "ka10080", token, {"stk_cd": code, "tic_scope": "3", "upd_stkpc_tp": "1"})
        print("keys:", list(dm.keys()), flush=True)
        mr = dm.get("stk_min_pole_chart_qry") or []
        print(f"봉수:{len(mr)} 앞3:", [{k: x.get(k) for k in ('cntr_tm', 'cur_prc')} for x in mr[:3]], flush=True)
