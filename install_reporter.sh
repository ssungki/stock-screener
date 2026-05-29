#!/usr/bin/env bash
# install_reporter.sh — 일일(평일 15:35 KST) + 주간(금요일 16:00 KST) 자동 리포트 설치(1회).
# `post_daily_report` = 그날 신호·MFE/MAE·룰결과를 디스코드에 표로 포스트(매일).
# `post_weekly_report` = 이번 주 SQLite 집계(시간대별·확산배수별)를 포스트(매주 금).
set -e
# sudo 로 실행시 $HOME 이 /root 로 바뀌어 잘못된 경로가 박히는 버그 방지 —
# 스크립트가 놓인 자리에서 APPDIR 을 자동 계산하고, User= 는 SUDO_USER 우선.
APPDIR="$(cd "$(dirname "$0")" && pwd)"
SVC_USER="${SUDO_USER:-$USER}"

sudo tee /etc/systemd/system/stock-screener-reporter.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Daily Report (Discord webhook post)

[Service]
Type=oneshot
User=$SVC_USER
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

# ── 일봉 돌파 스캔(평일 15:40 KST = 06:40 UTC, 일일리포트 5분 뒤) ──
sudo tee /etc/systemd/system/stock-screener-breakout.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Daily Breakout Scan (Discord)

[Service]
Type=oneshot
User=$SVC_USER
WorkingDirectory=$APPDIR
ExecStart=$APPDIR/.venv/bin/python $APPDIR/main.py post_breakout_scan
StandardOutput=journal
StandardError=journal
EOF
sudo tee /etc/systemd/system/stock-screener-breakout.timer >/dev/null <<EOF
[Unit]
Description=Stock Screener Daily Breakout Scan Timer (Mon-Fri 15:40 KST)

[Timer]
OnCalendar=Mon..Fri 06:40:00 UTC
Persistent=true
Unit=stock-screener-breakout.service

[Install]
WantedBy=timers.target
EOF

# ── 주간 리포트(금요일 16:00 KST = 07:00 UTC) ──
sudo tee /etc/systemd/system/stock-screener-weekly.service >/dev/null <<EOF
[Unit]
Description=Stock Screener Weekly Report (Discord)

[Service]
Type=oneshot
User=$SVC_USER
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
sudo systemctl enable --now stock-screener-breakout.timer
sudo systemctl enable --now stock-screener-weekly.timer

echo "=== 리포트 타이머 설치 완료 (일일 15:35 / 일봉돌파 15:40 / 주간 금 16:00 KST) ==="
systemctl list-timers --no-pager | grep stock-screener || true
echo "=== REPORTER_DONE ==="
