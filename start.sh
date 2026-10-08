#!/usr/bin/env bash
# Start laya-opencv on Linux / 启动 laya-opencv（Linux）
# Usage / 用法: bash start.sh
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "[!] Not installed yet. Run: bash install.sh"
  echo "[!] 还没有安装。请先运行: bash install.sh"
  exit 1
fi
exec .venv/bin/python app/launcher.py
