#!/bin/zsh
cd "$(dirname "$0")"

PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "找不到 Python 3。请先安装 Python 3。"
  read -k 1 "?按任意键关闭..."
  exit 1
fi

"$PYTHON_BIN" drive_bridge_gui.py --stop
read -k 1 "?按任意键关闭..."
