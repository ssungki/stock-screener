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
if [ "$LAST" = "$NEW" ]; then
    exit 0   # 변경 없음 — 조용히 종료
fi

# 풀기 (.env는 archive에 없어서 보존됨)
tar xzf "$TMP" --strip-components=1 -C "$APPDIR"

# 신택스 검증 — 깨진 코드 들어오면 재시작 안 해서 무중단 유지
if ! "$APPDIR/.venv/bin/python" -c "import ast
for f in ('main.py','kiwoom.py','analyzer.py','config.py','notifier.py'):
    ast.parse(open(f).read())" 2>/dev/null; then
    echo "$TS [update] 신택스 오류 — 재시작 보류 (이전 코드 그대로 가동 중)"
    exit 2
fi

if ! sudo /bin/systemctl restart stock-screener; then
    echo "$TS [update] 재시작 실패"
    exit 3
fi

echo "$NEW" > .last_update_md5
echo "$TS [update] 갱신 완료 (md5=${NEW:0:8})"

# install_reporter.sh 변경 감지 → 자동 재실행(새 systemd 타이머 자동 반영)
for inst in install_reporter.sh; do
    [ -f "$inst" ] || continue
    H_FILE=".${inst%.sh}_md5"
    NEW_H="$(md5sum "$inst" | awk '{print $1}')"
    LAST_H="$(cat "$H_FILE" 2>/dev/null || true)"
    if [ "$NEW_H" != "$LAST_H" ]; then
        chmod +x "$inst"
        if sudo /bin/bash "$APPDIR/$inst"; then
            echo "$NEW_H" > "$H_FILE"
            echo "$TS [update] $inst 자동 재실행 완료"
        else
            echo "$TS [update] $inst 실행 실패(권한? sudoers 확인)"
        fi
    fi
done
