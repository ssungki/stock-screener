#!/usr/bin/env bash
# install_reporter.sh — 일일(평일 15:35 KST) + 주간(금요일 16:00 KST) 자동 리포트 설치(1회).
# `post_daily_report` = 그날 신호·MFE/MAE·룰결과를 디스코드에 표로 포스트(매일).
# `post_weekly_report` = 이번 주 SQLite 집계(시간대별·확산배수별)를 포스트(매주 금).
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

# ── 주간 리포트(금요일 16:00 KST = 07:00 UTC) ──
sudo tee /etc/systemd/system/stock-screener-weekly.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Weekly Report (Discord)

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APPDIR
ExecStart=$APPDIR/.venv/bin/python $APPDIR/main.py post_weekly_report
StandardOutput=journal
StandardError=journal
EOF
sudo tee /etc/systemd/system/stock-screener-weekly.timer >/dev/null <<EOF
[Unit]
Description=Stock Screener Weekly Report Timer (Fri 16:00 KST)

[Timer]
OnCalendar=Fri 07:00:00 UTC
Persistent=true
Unit=stock-screener-weekly.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now stock-screener-reporter.timer
sudo systemctl enable --now stock-screener-weekly.timer

echo "=== 리포트 타이머 설치 완료 (일일 평일 15:35 / 주간 금 16:00 KST) ==="
systemctl list-timers --no-pager | grep stock-screener || true
echo "=== REPORTER_DONE ==="
