#!/usr/bin/env bash
set -euo pipefail

MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(cd "$MAC_DIR/app" && pwd)"
cd "$APP"

if [ ! -f .venv/bin/activate ]; then
  echo "未找到 $APP/.venv。请先执行: bash mac/setup_mac.sh"
  exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate
exec python main.py "$@"
