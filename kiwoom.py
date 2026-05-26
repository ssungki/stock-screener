"""키움 REST API 클라이언트.
- 접근토큰 발급 (POST /oauth2/token)
- WebSocket 실시간 조건검색 (LOGIN → CNSRLST → 실시간 조건 등록)
- 3분봉 차트 조회 (REST)

⚠️ 일부 메시지 스키마(실시간 조건 등록 trnm, 분봉 차트 api-id/필드명)는
   실제 키움 문서 기준으로 연결 테스트하며 확정 필요 — 표시는 [확인要].
"""
import json
import time
import threading
import requests
import websocket  # websocket-client
import config

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
    if d.get("return_code", 0) not in (0, None) and "token" not in d:
        raise RuntimeError(f"토큰 발급 실패: {d}")
    return d["token"]

# ─────────────────────── 3분봉 차트 (REST) ───────────────────────
def fetch_3min_closes(token, stk_cd, count=160):
    """종목의 3분봉 종가 리스트(오래된→최신). [확인要] api-id/필드명은 문서 대조 필요."""
    try:
        r = requests.post(
            f"{config.REST_BASE}/api/dostk/chart",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {token}",
                "api-id": "ka10080",          # 주식분봉차트조회요청 [확인要]
            },
            json={
                "stk_cd": stk_cd,
                "tic_scope": "3",             # 3분 [확인要]
                "upd_stkpc_tp": "1",
            },
            timeout=10,
        )
        d = r.json()
        # 응답 배열 키 이름은 문서 대조 필요. 흔한 후보들 방어적으로 탐색.
        rows = d.get("stk_min_pole_chart_qry") or d.get("output") or d.get("chart") or []
        closes = []
        for row in rows:
            v = row.get("cur_prc") or row.get("close") or row.get("stck_prpr")
            if v is None:
                continue
            closes.append(abs(float(str(v).replace(",", ""))))
        closes.reverse()  # 최신이 앞이면 뒤집어 오래된→최신
        return closes[-count:]
    except Exception as e:
        print(f"[chart] {stk_cd} 분봉 조회 실패: {e}", flush=True)
        return []

# ─────────────────────── WebSocket 조건검색 ───────────────────────
class ConditionStream:
    """실시간 조건검색 편입 종목코드를 on_codes(codes) 콜백으로 흘려보낸다."""
    def __init__(self, token, condition_name, on_codes):
        self.token = token
        self.condition_name = condition_name
        self.on_codes = on_codes
        self.ws = None
        self.target_seq = None
        self._stop = False

    def _send(self, obj):
        self.ws.send(json.dumps(obj))

    def on_open(self, ws):
        print("[ws] 연결됨 → LOGIN", flush=True)
        self._send({"trnm": "LOGIN", "token": self.token})

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        trnm = msg.get("trnm")

        if trnm == "LOGIN":
            if msg.get("return_code") == 0:
                print("[ws] 로그인 성공 → 조건식 목록 요청(CNSRLST)", flush=True)
                self._send({"trnm": "CNSRLST"})
            else:
                print(f"[ws] 로그인 실패: {msg}", flush=True)

        elif trnm == "CNSRLST":
            # data: [[seq, name], ...] 형태로 옴
            conds = msg.get("data") or []
            print(f"[ws] 조건식 {len(conds)}개: {conds}", flush=True)
            for item in conds:
                seq, name = (item[0], item[1]) if isinstance(item, list) else (item.get("seq"), item.get("name"))
                if name == self.condition_name:
                    self.target_seq = seq
            if self.target_seq is None:
                print(f"[ws] '{self.condition_name}' 조건식을 못 찾음. HTS에서 저장했는지 확인.", flush=True)
                return
            # 실시간 조건검색 등록 [확인要] trnm/필드명
            print(f"[ws] 조건식 seq={self.target_seq} 실시간 등록", flush=True)
            self._send({"trnm": "CNSRREQ", "seq": str(self.target_seq), "search_type": "1"})

        elif trnm in ("CNSRREQ", "REAL"):
            codes = self._extract_codes(msg)
            if codes:
                self.on_codes(codes)

        elif trnm == "PING":
            self._send({"trnm": "PONG"})

    def _extract_codes(self, msg):
        """편입 종목코드 추출 (스키마 방어적). [확인要] 실제 키 대조."""
        codes = []
        data = msg.get("data")
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    c = it.get("jmcode") or it.get("stk_cd") or it.get("9001")
                    # '편입'(insert)만 관심, '이탈'은 무시
                    if c and str(it.get("type", "I")).upper().startswith("I"):
                        codes.append(c.lstrip("A"))
                elif isinstance(it, str):
                    codes.append(it.lstrip("A"))
        return codes

    def on_error(self, ws, err):
        print(f"[ws] 에러: {err}", flush=True)

    def on_close(self, ws, code, reason):
        print(f"[ws] 종료: {code} {reason}", flush=True)

    def run_forever(self):
        """끊기면 자동 재연결."""
        while not self._stop:
            try:
                self.ws = websocket.WebSocketApp(
                    config.WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                print(f"[ws] run_forever 예외: {e}", flush=True)
            if not self._stop:
                print("[ws] 5초 후 재연결...", flush=True)
                time.sleep(5)

    def stop(self):
        self._stop = True
        if self.ws:
            self.ws.close()
