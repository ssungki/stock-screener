#!/usr/bin/env bash
# systemd 상시 실행 등록: 부팅/크래시 자동 재시작, 로그는 run.log 에 누적.
set -e
APPDIR="$HOME/stock-screener"
SVC="/etc/systemd/system/stock-screener.service"

sudo tee "$SVC" >/dev/null <<EOF
[Unit]
Description=Stock Screener (kiwoom 이평 수렴확산 알림)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APPDIR
ExecStart=$APPDIR/.venv/bin/python main.py
Restart=always
RestartSec=10
User=$USER
StandardOutput=append:$APPDIR/run.log
StandardError=append:$APPDIR/run.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable stock-screener >/dev/null 2>&1 || true
sudo systemctl restart stock-screener
sleep 3
echo "=== 상태 ==="
systemctl --no-pager status stock-screener | head -8
echo "=== 최근 로그 ==="
tail -n 8 "$APPDIR/run.log" 2>/dev/null || true
echo "=== SERVICE_DONE ==="
