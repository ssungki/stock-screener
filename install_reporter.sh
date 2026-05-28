#!/usr/bin/env bash
# install_reporter.sh — 매일 15:35 KST(=06:35 UTC) 자동 일일 리포트 설치(1회만 실행).
# `python main.py post_daily_report` 를 평일 장 마감 5분 후 실행 → 디스코드 웹훅에 포스트.
set -e
APPDIR="$HOME/stock-screener"

sudo tee /etc/systemd/system/stock-screener-reporter.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Daily Report (Discord webhook post)

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APPDIR
ExecStart=$APPDIR/.venv/bin/python $APPDIR/main.py post_daily_report
StandardOutput=journal
StandardError=journal
EOF

# 평일 06:35 UTC = 15:35 KST (서버 TZ가 UTC라 그대로)
sudo tee /etc/systemd/system/stock-screener-reporter.timer >/dev/null <<EOF
[Unit]
Description=Stock Screener Daily Report Timer (weekdays 15:35 KST)

[Timer]
OnCalendar=Mon..Fri 06:35:00 UTC
Persistent=true
Unit=stock-screener-reporter.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now stock-screener-reporter.timer

echo "=== 일일 리포트 타이머 설치 완료 (평일 15:35 KST 자동) ==="
systemctl list-timers --no-pager | grep stock-screener || true
echo "=== REPORTER_DONE ==="
