"""알람 영구 로깅(SQLite). journalctl만으론 VM 폭사 시 다 날아가서 데이터 분실.

스키마: 알람 1건 = 1행. 사후(장 마감 후)에 MFE/MAE·룰결과를 같은 행에 채울 수 있게 컬럼 비워둠.
"""
import os
import sqlite3
import time as _time
from pathlib import Path

DB_PATH = Path(os.path.expanduser("~")) / "stock-screener" / "data" / "alerts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_kst        TEXT NOT NULL,        -- YYYYMMDD
    time_kst        TEXT NOT NULL,        -- HHMMSS
    code            TEXT NOT NULL,
    name            TEXT,
    buy_price       REAL,
    expansion_x     REAL,
    recent_min_w    REAL,                 -- 수렴 최저 밴드폭(원시, 클리핑 전)
    fired_at        INTEGER,              -- unix epoch (UTC)
    -- 사후 분석용(나중 채움)
    mfe_pct         REAL,
    mae_pct         REAL,
    mfe_time        TEXT,
    mae_time        TEXT,
    close_pct       REAL,                 -- 종일보유 수익률
    rule_kind       TEXT,                 -- TAKE / STOP / HOLD
    rule_pct        REAL,
    rule_time       TEXT,
    updated_at      INTEGER,
    UNIQUE(date_kst, time_kst, code)
);
CREATE INDEX IF NOT EXISTS idx_alerts_date ON alerts(date_kst);

-- 2026-06-14: 종가베팅 paper trading 1개월 검증용.
-- 매수일(저항+4% 신호 발생일) 종가 매수 → 익일 시초가 매도.
CREATE TABLE IF NOT EXISTS paper_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    buy_date_kst    TEXT NOT NULL,        -- 신호일/매수일 YYYYMMDD
    code            TEXT NOT NULL,
    name            TEXT,
    signal_kind     TEXT,                 -- RESIST4 / BOX / TREND
    buy_price       REAL NOT NULL,        -- 신호일 종가
    pct_above_resist REAL,                -- 신호 시점 저항 대비 %
    sell_date_kst   TEXT,                 -- 매도일(보통 buy_date+1영업일)
    sell_price      REAL,                 -- 익일 시초가
    return_pct      REAL,                 -- (sell-buy)/buy*100
    return_pct_net  REAL,                 -- 수수료 0.4% 차감
    capital_share   REAL,                 -- 그날 자본 중 이 거래 비중(0~1)
    status          TEXT,                 -- OPEN / CLOSED
    created_at      INTEGER,
    closed_at       INTEGER,
    UNIQUE(buy_date_kst, code)
);
CREATE INDEX IF NOT EXISTS idx_paper_buy_date ON paper_trades(buy_date_kst);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_trades(status);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.executescript(_SCHEMA)
    return c


def log_alert(date_kst, time_kst, code, name, buy_price, expansion_x, recent_min_w):
    """알람 1건 저장. 중복(같은 날짜·시각·종목)이면 무시."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO alerts "
                "(date_kst, time_kst, code, name, buy_price, expansion_x, recent_min_w, fired_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date_kst, time_kst, code, name, buy_price, expansion_x, recent_min_w, int(_time.time()))
            )
    except Exception as e:
        print(f"[storage] log_alert 실패: {e}", flush=True)


def fetch_alerts(date_kst):
    """특정 날짜(YYYYMMDD)의 알람 행들."""
    try:
        with _conn() as c:
            cur = c.execute(
                "SELECT id, date_kst, time_kst, code, name, buy_price, expansion_x, recent_min_w, "
                "mfe_pct, mae_pct, mfe_time, mae_time, close_pct, rule_kind, rule_pct, rule_time "
                "FROM alerts WHERE date_kst=? ORDER BY time_kst",
                (date_kst,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        print(f"[storage] fetch_alerts 실패: {e}", flush=True)
        return []


def update_outcomes(date_kst, code, time_kst, **fields):
    """장 마감 후 사후 분석 결과(MFE/MAE/룰)를 같은 행에 채움."""
    if not fields:
        return
    cols = list(fields.keys()) + ["updated_at"]
    vals = list(fields.values()) + [int(_time.time())]
    set_clause = ", ".join(f"{k}=?" for k in cols)
    try:
        with _conn() as c:
            c.execute(
                f"UPDATE alerts SET {set_clause} "
                "WHERE date_kst=? AND time_kst=? AND code=?",
                vals + [date_kst, time_kst, code])
    except Exception as e:
        print(f"[storage] update_outcomes 실패: {e}", flush=True)


FEE_PCT = 0.4  # 매수+매도 수수료/세금 합 약 0.4% (한국 주식 기준)


def open_paper_trade(buy_date_kst, code, name, signal_kind, buy_price,
                     pct_above_resist=None, capital_share=1.0):
    """신호 발생일 종가에 paper 매수 기록. 중복(같은 날·종목)은 무시."""
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO paper_trades "
                "(buy_date_kst, code, name, signal_kind, buy_price, "
                " pct_above_resist, capital_share, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)",
                (buy_date_kst, code, name, signal_kind, buy_price,
                 pct_above_resist, capital_share, int(_time.time()))
            )
    except Exception as e:
        print(f"[storage] open_paper_trade 실패: {e}", flush=True)


def close_paper_trade(buy_date_kst, code, sell_date_kst, sell_price):
    """익일 시초가에 paper 매도 기록 + 수익률 계산. 이미 CLOSED 면 무시."""
    try:
        with _conn() as c:
            cur = c.execute(
                "SELECT buy_price FROM paper_trades "
                "WHERE buy_date_kst=? AND code=? AND status='OPEN'",
                (buy_date_kst, code))
            row = cur.fetchone()
            if not row:
                return False
            buy_price = row[0]
            ret = (sell_price - buy_price) / buy_price * 100
            net = ret - FEE_PCT
            c.execute(
                "UPDATE paper_trades SET sell_date_kst=?, sell_price=?, "
                "return_pct=?, return_pct_net=?, status='CLOSED', closed_at=? "
                "WHERE buy_date_kst=? AND code=?",
                (sell_date_kst, sell_price, ret, net, int(_time.time()),
                 buy_date_kst, code))
            return True
    except Exception as e:
        print(f"[storage] close_paper_trade 실패: {e}", flush=True)
        return False


def fetch_paper_trades(status=None, since_date=None):
    """paper 거래 조회. status='OPEN'/'CLOSED' 또는 None(전체). since_date=YYYYMMDD."""
    try:
        with _conn() as c:
            sql = ("SELECT id, buy_date_kst, code, name, signal_kind, buy_price, "
                   "pct_above_resist, sell_date_kst, sell_price, return_pct, "
                   "return_pct_net, capital_share, status, created_at, closed_at "
                   "FROM paper_trades")
            params = []
            where = []
            if status:
                where.append("status=?"); params.append(status)
            if since_date:
                where.append("buy_date_kst>=?"); params.append(since_date)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY buy_date_kst, code"
            cur = c.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        print(f"[storage] fetch_paper_trades 실패: {e}", flush=True)
        return []


def recent_dates(limit=14):
    """최근 N일치 (date_kst, count) — 일별 리포트 인덱스용."""
    try:
        with _conn() as c:
            cur = c.execute(
                "SELECT date_kst, COUNT(*) FROM alerts "
                "GROUP BY date_kst ORDER BY date_kst DESC LIMIT ?", (limit,))
            return cur.fetchall()
    except Exception as e:
        print(f"[storage] recent_dates 실패: {e}", flush=True)
        return []
