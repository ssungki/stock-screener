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
from datetime import datetime, timezone, timedelta
import time
import requests
import config

CHART_EP = f"{config.REST_BASE}/api/dostk/chart"
RANK_EP = f"{config.REST_BASE}/api/dostk/rkinfo"
KST = timezone(timedelta(hours=9))

# ETF/ETN 은 후보에서 제외 (이름 앞부분으로 판별)
_ETF_PREFIXES = ("KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL ", "ACE ",
                 "RISE", "PLUS", "KOSEF", "TIMEFOLIO", "WOORI", "히어로즈", "마이티",
                 "BNK", "FOCUS", "TREX", "KIWOOM", "VITA", "1Q", "ITF")


def _is_etf_like(name):
    n = (name or "").upper()
    return any(n.startswith(p) for p in _ETF_PREFIXES) or "ETN" in n


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


def _post(endpoint, api_id, token, body, timeout=10, extra_headers=None, with_headers=False):
    """공통 POST. (응답 dict 반환, 실패 시 예외)

    extra_headers: 연속조회용 cont-yn/next-key 등 추가 요청헤더.
    with_headers=True 면 (json, 응답헤더) 튜플 반환.
    """
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": api_id,
    }
    if extra_headers:
        headers.update(extra_headers)
    r = requests.post(endpoint, headers=headers, json=body, timeout=timeout)
    r.raise_for_status()
    if with_headers:
        return r.json(), r.headers
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
    """거래대금 상위 (종목코드, 종목명) 리스트(상위→하위). 최대 count개.

    키움은 한 호출에 한 페이지만 주므로, cont-yn/next-key로 연속조회해
    count개가 찰 때까지 다음 페이지를 이어받는다.
    """
    body = {
        "mrkt_tp": config.MRKT_TP,          # 000:전체 001:코스피 101:코스닥
        "mang_stk_incls": "0",              # 관리종목 미포함
        "stex_tp": config.STEX_TP,          # 1:KRX 2:NXT 3:통합
    }
    out = []
    extra = None
    for _ in range(10):                     # 페이지 최대 10회(무한루프 방지)
        d, hdr = _post(RANK_EP, "ka10032", token, body,
                       extra_headers=extra, with_headers=True)
        rows = d.get("trde_prica_upper") or []
        for row in rows:
            c = row.get("stk_cd")
            nm = (row.get("stk_nm") or "").strip()
            if not c or _is_etf_like(nm):              # ETF/ETN 제외
                continue
            out.append((c.lstrip("A").strip(), nm))
            if len(out) >= count:
                return out
        cont = (hdr.get("cont-yn") or "N").strip()
        next_key = (hdr.get("next-key") or "").strip()
        if cont != "Y" or not next_key or not rows:    # 더 줄 게 없으면 종료
            break
        extra = {"cont-yn": "Y", "next-key": next_key}
        time.sleep(config.REQ_DELAY_SEC)
    return out


# ─────────────────── 일봉 (ka10081) — 추세 필터 ───────────────────
def fetch_daily_closes(token, stk_cd, count=60):
    """일봉 종가 리스트(오래된→최신)."""
    try:
        d = _post(CHART_EP, "ka10081", token, {
            "stk_cd": stk_cd,
            "base_dt": datetime.now(KST).strftime("%Y%m%d"),  # 기준일자(오늘) — 빈값이면 안 옴
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
def fetch_intraday_closes(token, stk_cd, count=160):
    """분봉 종가 리스트(오래된→최신). 봉 단위는 config.TICK_MIN(분)."""
    try:
        d = _post(CHART_EP, "ka10080", token, {
            "stk_cd": stk_cd,
            "tic_scope": str(config.TICK_MIN),   # 분봉 단위(1=1분, 3=3분)
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

    code = (rows[0].get("stk_cd") or "").lstrip("A") if rows else "005930"  # 장마감 등으로 비면 삼성전자로 차트 형식 확인
    if True:
        print(f"\n── 일봉(ka10081) {code} ──", flush=True)
        dd = _post(CHART_EP, "ka10081", token, {
            "stk_cd": code, "base_dt": datetime.now(KST).strftime("%Y%m%d"), "upd_stkpc_tp": "1"})
        print("keys:", list(dd.keys()), "rc:", dd.get("return_code"), dd.get("return_msg"), flush=True)
        dr = dd.get("stk_dt_pole_chart_qry") or []
        print(f"봉수:{len(dr)} 앞3:", [{k: x.get(k) for k in ('dt', 'cur_prc')} for x in dr[:3]], flush=True)

        print(f"\n── 3분봉(ka10080) {code} ──", flush=True)
        dm = _post(CHART_EP, "ka10080", token, {"stk_cd": code, "tic_scope": "3", "upd_stkpc_tp": "1"})
        print("keys:", list(dm.keys()), flush=True)
        mr = dm.get("stk_min_pole_chart_qry") or []
        print(f"봉수:{len(mr)} 앞3:", [{k: x.get(k) for k in ('cntr_tm', 'cur_prc')} for x in mr[:3]], flush=True)
