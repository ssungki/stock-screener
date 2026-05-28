#!/usr/bin/env bash
# update.sh — GitHub master tarball을 받아 변경시 신택스 검증 후 재시작.
# systemd 타이머(stock-screener-updater.timer)가 5분마다 호출.
# 변경 없으면 조용히 종료, 신택스 깨지면 재시작 보류.
set -u
APPDIR="$HOME/stock-screener"
TMP="/tmp/screener_master.tar.gz"
URL="https://github.com/ssungki/stock-screener/archive/refs/heads/master.tar.gz"
TS="$(date '+%F %T')"

cd "$APPDIR" || { echo "$TS [update] $APPDIR 없음"; exit 1; }

LAST="$(cat .last_update_md5 2>/dev/null || true)"
if ! curl -sLfo "$TMP" "$URL"; then
    echo "$TS [update] curl 실패"
    exit 1
fi
NEW="$(md5sum "$TMP" | awk '{print $1}')"

# 1) master 변경시: 풀기 + 신택스 검증 + 봇 재시작
if [ "$LAST" != "$NEW" ]; then
    tar xzf "$TMP" --strip-components=1 -C "$APPDIR"
    if ! "$APPDIR/.venv/bin/python" -c "import ast
for f in ('main.py','kiwoom.py','analyzer.py','config.py','notifier.py'):
    ast.parse(open(f).read())" 2>/dev/null; then
        echo "$TS [update] 신택스 오류 — 재시작 보류 (이전 코드 그대로 가동 중)"
    else
        if sudo /bin/systemctl restart stock-screener; then
            echo "$NEW" > .last_update_md5
            echo "$TS [update] 코드 갱신 완료 (md5=${NEW:0:8})"
        else
            echo "$TS [update] 재시작 실패"
        fi
    fi
fi

# 2) install_*.sh 변경시 자동 재실행(master 변경 여부와 무관 — 새 timer 자동 반영)
for inst in install_reporter.sh; do
    [ -f "$APPDIR/$inst" ] || continue
    H_FILE="$APPDIR/.${inst%.sh}_md5"
    NEW_H="$(md5sum "$APPDIR/$inst" | awk '{print $1}')"
    LAST_H="$(cat "$H_FILE" 2>/dev/null || true)"
    if [ "$NEW_H" != "$LAST_H" ]; then
        chmod +x "$APPDIR/$inst"
        if sudo /bin/bash "$APPDIR/$inst"; then
            echo "$NEW_H" > "$H_FILE"
            echo "$TS [update] $inst 자동 재실행 완료(새 systemd 반영)"
        else
            echo "$TS [update] $inst 실행 실패(sudoers 확인 필요)"
        fi
    fi
done
