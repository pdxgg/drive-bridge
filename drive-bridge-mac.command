#!/bin/zsh
cd "$(dirname "$0")"
LOG_DIR="${TMPDIR:-/tmp}/drive-bridge"
LOG_FILE="$LOG_DIR/drive-bridge.log"
mkdir -p "$LOG_DIR"

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

echo "正在启动 Drive Bridge macOS 界面..."
echo "如果浏览器没有自动打开，请复制终端里显示的 http://127.0.0.1:xxxxx 地址到浏览器。"
echo "Starting Drive Bridge with $PYTHON_BIN at $(date)" > "$LOG_FILE"
"$PYTHON_BIN" drive_bridge_gui.py 2>&1 | tee -a "$LOG_FILE"
