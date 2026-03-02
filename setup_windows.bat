@echo off
cd /d "%~dp0"

echo ========================================
echo   ins_to_drive - Windows Setup
echo ========================================
echo.

echo [1/3] Removing old .venv if exists...
if exist ".venv" (
    rmdir /s /q .venv
    echo Done.
) else (
    echo Skip.
)
echo.

echo [2/3] Creating virtual environment...
python -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" (
    echo Trying py launcher...
    py -m venv .venv 2>nul
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERROR: Python not found.
    echo Please install Python from https://www.python.org/downloads/
    echo During install, CHECK "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
echo OK.
echo.

echo [3/3] Installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
echo.

echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo To run next time, use CMD and run:
echo   cd /d "C:\Users\ASUS\OneDrive - bfsu.edu.cn\cursor\ins_to_drive"
echo   .venv\Scripts\activate.bat
echo   python main.py video
echo.
pause
