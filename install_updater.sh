#!/usr/bin/env bash
# install_updater.sh — GitHub auto-pull "우편함" 설치(1회만 실행).
# - update.sh 실행권한 부여
# - opc 사용자에게 stock-screener 재시작만 NOPASSWD 권한 부여(최소권한)
# - systemd updater.service + updater.timer 등록(5분마다)
set -e
APPDIR="$HOME/stock-screener"
chmod +x "$APPDIR/update.sh"

# sudoers: opc 가 패스워드 없이 (1) stock-screener 재시작 (2) install_reporter.sh 실행만 가능.
# install_*.sh 자동 재실행으로 systemd 타이머 변경도 우편함이 처리하게 함(최소권한 유지).
sudo tee /etc/sudoers.d/stock-screener-updater >/dev/null <<'SUDOERS'
opc ALL=(root) NOPASSWD: /bin/systemctl restart stock-screener
opc ALL=(root) NOPASSWD: /bin/bash /home/opc/stock-screener/install_reporter.sh
SUDOERS
sudo chmod 0440 /etc/sudoers.d/stock-screener-updater

# 업데이터 서비스(oneshot)
sudo tee /etc/systemd/system/stock-screener-updater.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Auto Update (GitHub pull)

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APPDIR
ExecStart=/bin/bash $APPDIR/update.sh
StandardOutput=journal
StandardError=journal
EOF

# 5분 주기 타이머
sudo tee /etc/systemd/system/stock-screener-updater.timer >/dev/null <<EOF
[Unit]
Description=Stock Screener Auto Update Timer (5min)

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=stock-screener-updater.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now stock-screener-updater.timer

echo "=== 우편함 설치 완료 ==="
systemctl list-timers --no-pager | grep stock-screener || true
echo "=== 즉시 1회 실행 ==="
sudo /bin/systemctl start stock-screener-updater.service
sleep 3
journalctl -u stock-screener-updater -n 10 --no-pager
echo "=== UPDATER_DONE ==="
