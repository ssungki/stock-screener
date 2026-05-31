#!/usr/bin/env bash
# manager_trigger.sh — 매니저(Claude)가 디스코드 요청을 즉시 우편함에 던지기.
#   사용: ./tools/manager_trigger.sh <command>
#   command: post_daily_report | post_weekly_report | post_breakout_scan | backfill
# 동작: triggers/<ts>_<cmd>.flag 파일을 만들어 git push.
#       5분 내 stock-screener-updater.timer 가 pull → update.sh 가 cmd 1회 실행.
set -e
cmd="${1:?command required (post_daily_report|post_weekly_report|post_breakout_scan|backfill)}"
case "$cmd" in
    post_daily_report|post_weekly_report|post_breakout_scan|backfill) ;;
    *) echo "지원되지 않는 명령: $cmd"; exit 1 ;;
esac

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
ts="$(date '+%Y%m%d_%H%M%S')"
fname="triggers/${ts}_${cmd}.flag"
echo "$cmd" > "$fname"
git add "$fname"
git commit -m "trigger: $cmd ($ts)"
git push origin master
echo "✅ 트리거 push: $fname"
echo "   서버 우편함이 5분 내 pull → 실행 → 디스코드에 결과 포스트"
