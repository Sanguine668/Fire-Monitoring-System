#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m pip install -r requirements.txt
printf '\n[FireGuard AI] 启动完成后访问 http://127.0.0.1:8000\n\n'
python run.py
