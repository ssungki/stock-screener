#!/usr/bin/env bash
# install_updater.sh — GitHub auto-pull "우편함" 설치(1회만 실행).
# - update.sh 실행권한 부여
# - opc 사용자에게 stock-screener 재시작만 NOPASSWD 권한 부여(최소권한)
# - systemd updater.service + updater.timer 등록(5분마다)
set -e
# sudo 실행 시 $HOME 이 /root 로 리셋되는 문제 회피 — 스크립트 위치 기반.
APPDIR="$(cd "$(dirname "$0")" && pwd)"
SVC_USER="${SUDO_USER:-$USER}"
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
User=$SVC_USER
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
# 사용자 sudoers 변경 즉시 적용을 위해 install_reporter.sh도 같은 실행에서 한 번 돌림
# (지금 sudoers에 막 NOPASSWD 등록했으니 바로 됨)
if [ -f "$APPDIR/install_reporter.sh" ]; then
    chmod +x "$APPDIR/install_reporter.sh"
    echo "=== install_reporter.sh 동시 실행(타이머 일괄 등록) ==="
    sudo /bin/bash "$APPDIR/install_reporter.sh" || echo "install_reporter.sh 실패 — 권한 확인"
    # md5 기록(update.sh 가 중복 실행 안 하게)
    md5sum "$APPDIR/install_reporter.sh" | awk '{print $1}' > "$APPDIR/.install_reporter_md5"
fi
systemctl list-timers --no-pager | grep stock-screener || true
echo "=== 즉시 1회 실행 ==="
sudo /bin/systemctl start stock-screener-updater.service
sleep 3
journalctl -u stock-screener-updater -n 10 --no-pager
echo "=== UPDATER_DONE ==="
