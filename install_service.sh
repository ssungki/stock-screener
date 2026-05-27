#!/usr/bin/env bash
# systemd 상시 실행 등록: 부팅/크래시 자동 재시작, 로그는 run.log 에 누적.
set -e
APPDIR="$HOME/stock-screener"
SVC="/etc/systemd/system/stock-screener.service"

# Oracle Linux 9 SELinux는 systemd가 홈폴더의 파일을 실행/기록하는 것을 막는다(203/EXEC, 209/STDOUT).
# 개인용 단일 봇 VM이므로 permissive로 전환해 차단을 해제한다.
sudo setenforce 0 2>/dev/null || true
sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config 2>/dev/null || true

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
StandardOutput=journal
StandardError=journal

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
journalctl -u stock-screener -n 8 --no-pager 2>/dev/null || true
echo "=== SERVICE_DONE ==="
