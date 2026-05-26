#!/usr/bin/env bash
# 서버 1회 세팅: 패키지 설치 → 코드 받기 → 파이썬 가상환경 + 의존성
set -e

echo "[setup] 패키지 설치 (git / python3 / pip)..."
sudo dnf install -y git python3 python3-pip >/dev/null 2>&1 || sudo dnf install -y git python3 python3-pip

cd ~
echo "[setup] 코드 받기..."
rm -rf stock-screener
git clone https://github.com/ssungki/stock-screener.git
cd stock-screener

echo "[setup] 파이썬 환경 구성..."
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

# .env 가 없으면 예시로 만들어 둠 (값은 나중에 채움)
[ -f .env ] || cp .env.example .env

echo ""
echo "=== DONE_SETUP ==="
echo "다음: nano .env 로 키 입력"
