@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    python main.py %*
) else if exist ".venv\bin\activate" (
    echo 检测到 Mac 创建的虚拟环境，Windows 无法使用。
    echo 正在删除并重新创建...
    rmdir /s /q .venv 2>nul
    python -m venv .venv
    if exist ".venv\Scripts\activate.bat" (
        call .venv\Scripts\activate.bat
        pip install -r requirements.txt
        python main.py %*
    ) else (
        echo 创建失败，使用系统 Python 运行：
        python main.py %*
    )
) else (
    echo 未检测到虚拟环境，正在创建...
    python -m venv .venv
    if exist ".venv\Scripts\activate.bat" (
        call .venv\Scripts\activate.bat
        pip install -r requirements.txt
        python main.py %*
    ) else (
        echo 创建失败，使用系统 Python 运行：
        python main.py %*
    )
)

pause
