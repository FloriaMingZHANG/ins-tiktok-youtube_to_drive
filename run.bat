@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    python main.py
) else (
    echo 未检测到虚拟环境，请先运行：python -m venv .venv  然后  .venv\Scripts\activate  然后  pip install -r requirements.txt
    python main.py
)

pause
