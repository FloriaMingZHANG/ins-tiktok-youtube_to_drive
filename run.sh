#!/bin/bash
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    python3 main.py
else
    echo "未检测到虚拟环境，请先运行："
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    python3 main.py
fi
