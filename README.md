# 주식 검색기 (실시간 이평 수렴→확산 알림기)

키움 REST API 실시간 조건검색으로 후보 종목을 받아, 3분봉에서 **이평선(5·10·20·60·120) 수렴(스퀴즈) → 확산(정배열 돌파)** 패턴을 포착하면 **디스코드 + 카카오톡**으로 알린다. 매매는 하지 않음(알림 전용). 클라우드 서버(오라클 무료티어, 춘천)에서 24시간 상주.

## 구성
- `kiwoom.py` — 토큰 발급, WebSocket 실시간 조건검색, 3분봉 차트 조회
- `analyzer.py` — 수렴→확산 판정 로직
- `notifier.py` — 디스코드 웹훅 + 카카오 "나에게 보내기"(토큰 자동갱신)
- `main.py` — 오케스트레이션
- `config.py` / `.env` — 설정·비밀키

## 흐름
```
LOGIN → 조건식 목록(CNSRLST) → 대상 조건식 실시간 등록
   → 편입 종목코드 수신 → 각 종목 3분봉 조회 → analyzer.detect()
   → 신호면 디코+카톡 알림 (종목별 쿨다운)
```
1차 필터(일봉 상승 + 이평 수렴 근접)는 **HTS(영웅문) 조건검색식**에서 만들어 저장.
정밀 판정(확산 돌파 순간)은 이 프로그램의 `analyzer.py`가 담당.

## 셋업 (오라클 Ubuntu 서버 기준)
```bash
sudo apt update && sudo apt install -y python3-venv
git clone <repo> stock_screener   # 또는 scp 로 업로드
cd stock_screener
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # 키 입력 (앱키/시크릿/웹훅/카카오)
python3 main.py
```

### 상시 실행 (systemd) — 부팅/크래시 자동 재시작
`/etc/systemd/system/stock-screener.service`:
```ini
[Unit]
Description=Stock Screener
After=network-online.target

[Service]
WorkingDirectory=/home/ubuntu/stock_screener
ExecStart=/home/ubuntu/stock_screener/.venv/bin/python3 main.py
Restart=always
RestartSec=5
User=ubuntu

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now stock-screener
journalctl -u stock-screener -f   # 로그
```
> 장중에만 돌리려면 systemd timer 또는 main 내 시간체크로 09:00~15:30(평일) 가동.

## ⚠️ 연결 테스트 때 확정할 항목 ([확인要] 표시)
- 분봉 차트 api-id(`ka10080`)·요청/응답 필드명
- 실시간 조건검색 등록 메시지(`CNSRREQ`)·편입종목 응답 스키마
- 위는 키움 공식 문서(openapi.kiwoom.com) + 실제 응답 로그로 대조해 수정.

## 보안
- `.env`(앱키·시크릿·카카오 토큰)는 **절대 깃/채팅 노출 금지**. 서버에만 둠.
- 키움 API는 **서버 공인 IP 화이트리스트** 등록 필요(오라클 고정 IP).
