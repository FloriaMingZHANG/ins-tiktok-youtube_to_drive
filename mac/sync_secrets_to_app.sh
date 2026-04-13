#!/usr/bin/env bash
# 把仓库根目录已有的密钥/配置复制到 mac/app/（你在 mac/app 里运行时 cwd 在这里，程序默认读当前目录下的文件）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/mac/app"

if [ ! -d "$APP" ]; then
  echo "错误: 未找到 $APP，请先确认 mac/app 目录存在。"
  exit 1
fi

echo "源目录: $ROOT"
echo "目标目录: $APP"
echo ""

copied=0
for f in credentials.json cookies.txt client_secret.json token.json .env; do
  src="$ROOT/$f"
  if [ -f "$src" ]; then
    cp "$src" "$APP/$f"
    echo "已复制: $f"
    copied=$((copied + 1))
  else
    echo "跳过（根目录没有该文件）: $f"
  fi
done

echo ""
if [ "$copied" -eq 0 ]; then
  echo "根目录下没有找到可复制的文件。"
  echo "请先把 Google 服务账号密钥保存为仓库根目录的 credentials.json，再重新运行本脚本；"
  echo "或手动把文件放进: $APP"
  exit 1
fi

echo "完成。若尚未配置环境变量，请在 mac/app 下执行:"
echo "  cd \"$APP\" && cp -n config.example.env .env"
echo "（若已有 .env 被复制，可直接编辑 mac/app/.env）"
