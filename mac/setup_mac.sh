#!/usr/bin/env bash
set -euo pipefail

MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(cd "$MAC_DIR/app" && pwd)"
cd "$APP"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3。请先安装 Python 3（https://www.python.org/downloads/ 或 brew install python）。"
  exit 1
fi

# Windows 同步过来的 venv 只有 Scripts/，没有 bin/activate
if [ -d .venv ] && [ ! -f .venv/bin/activate ]; then
  echo "当前 .venv 不是 Mac 可用的虚拟环境，将删除并重建: $APP/.venv"
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  echo "创建虚拟环境: $APP/.venv"
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

echo "安装/更新依赖 (requirements.txt)..."
pip install -r requirements.txt

echo ""
echo "完成。工作目录为: $APP"
echo "  cd \"$APP\" && source .venv/bin/activate && python main.py"
echo "或:"
echo "  bash mac/run_main.sh"
