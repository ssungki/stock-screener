#!/usr/bin/env bash
# 서버 1회 세팅 (dnf 없이 — 1GB 머신에서도 가볍고 빠르게)
# Oracle Linux 9 에는 python3 가 기본 설치돼 있고, 코드는 git 대신 curl 로 받는다.
set -e

cd ~
echo "[1/4] 코드 내려받기 (curl tarball)..."
rm -rf stock-screener stock-screener-master
curl -sL https://github.com/ssungki/stock-screener/archive/refs/heads/master.tar.gz | tar xz
mv stock-screener-master stock-screener
cd stock-screener

echo "[2/4] 파이썬 가상환경 만들기..."
python3 -m venv .venv

echo "[3/4] 의존성 설치 (requests, websocket-client)..."
.venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "[4/4] .env 준비..."
[ -f .env ] || cp .env.example .env

echo ""
echo "=== DONE_SETUP ==="
