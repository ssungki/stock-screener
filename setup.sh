#!/usr/bin/env bash
# 서버 1회 세팅: (저메모리 대비)스왑 → 필요한 패키지만 설치 → 코드 → 파이썬 환경
set -e

# ── 1GB 머신 대비: 2G 스왑 없으면 추가 (dnf OOM 방지) ──
if ! sudo swapon --show 2>/dev/null | grep -q .; then
  echo "[setup] 스왑 2G 추가..."
  if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
  fi
  sudo swapon /swapfile 2>/dev/null || true
fi

# ── 이미 있는 건 건너뛰고 없는 것만 설치 ──
need=""
command -v git >/dev/null 2>&1 || need="$need git"
command -v python3 >/dev/null 2>&1 || need="$need python3"
python3 -m pip --version >/dev/null 2>&1 || need="$need python3-pip"
if [ -n "$need" ]; then
  echo "[setup] 패키지 설치:$need"
  sudo dnf install -y $need
else
  echo "[setup] git/python3/pip 이미 설치됨 — 건너뜀"
fi

cd ~
echo "[setup] 코드 받기..."
rm -rf stock-screener
git clone https://github.com/ssungki/stock-screener.git
cd stock-screener

echo "[setup] 파이썬 환경 구성..."
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

[ -f .env ] || cp .env.example .env

echo ""
echo "=== DONE_SETUP ==="
