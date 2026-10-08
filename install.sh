#!/usr/bin/env bash
# laya-opencv installer for Linux / laya-opencv 安装脚本（Linux）
# Usage / 用法: bash install.sh
set -u
cd "$(dirname "$0")"

PY=""
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  for cand in python3.12 python3.11 python3.13 python3.10 python3.14 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PY="$cand"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo
  echo "[!] Python 3.10 or newer was not found. Install it first:"
  echo "[!] 没有找到 Python 3.10 或更高版本。请先安装："
  echo "    Debian / Ubuntu:  sudo apt install python3 python3-venv"
  echo "    Fedora / RHEL:    sudo dnf install python3"
  echo "    Arch:             sudo pacman -S python"
  exit 1
fi

if [ "$PY" != ".venv/bin/python" ] && ! "$PY" -c 'import venv, ensurepip' >/dev/null 2>&1; then
  echo
  echo "[!] This Python has no venv module. On Debian / Ubuntu run:"
  echo "[!] 这个 Python 缺少 venv 模块。Debian / Ubuntu 请先执行："
  echo "    sudo apt install python3-venv"
  exit 1
fi

"$PY" app/install.py "$@"
code=$?
if [ $code -ne 0 ]; then
  echo
  echo "[!] Installation did not finish. Fix the error above and run bash install.sh again; finished steps are skipped."
  echo "[!] 安装没有完成。修复上面的问题后重新运行 bash install.sh，已完成的步骤会自动跳过。"
  exit $code
fi
chmod +x start.sh 2>/dev/null || true
