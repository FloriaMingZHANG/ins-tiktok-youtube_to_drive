@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   视频批量上传到 Google Drive
echo ========================================
echo.

:: ---- 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [错误] 未检测到 Python！
        echo.
        echo 请先安装 Python：
        echo   1. 用浏览器打开 https://www.python.org/downloads/
        echo   2. 下载并安装（安装时务必勾选 "Add Python to PATH"）
        echo   3. 安装完成后重新双击本文件
        echo.
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

:: ---- 检查 credentials.json ----
if not exist "credentials.json" (
    echo [提示] 未找到 credentials.json（Google 服务账号密钥）
    echo.
    echo 请按以下步骤操作：
    echo   1. 打开 https://console.cloud.google.com/
    echo   2. 新建项目，启用 Google Sheets API 和 Google Drive API
    echo   3. 创建服务账号，下载密钥 JSON 文件
    echo   4. 将该文件重命名为 credentials.json，放到本文件夹里
    echo   5. 把你的 Google 表格和 Drive 文件夹共享给密钥里的邮箱地址
    echo   6. 配置好后重新双击本文件
    echo.
    echo 详细步骤请参考 README.md
    echo.
    pause
    exit /b 1
)

:: ---- 检查 .env ----
if not exist ".env" (
    echo [提示] 未找到配置文件 .env，正在自动创建...
    copy "config.example.env" ".env" >nul
    echo 已创建 .env，正在用记事本打开，请填写你的表格地址等信息后保存。
    echo 保存并关闭记事本后，程序会自动继续。
    echo.
    notepad ".env"
    echo.
    echo 记事本已关闭，继续运行...
    echo.
)

:: ---- 建虚拟环境 / 安装依赖 ----
if not exist ".venv\Scripts\activate.bat" (
    echo [首次运行] 正在安装依赖，请稍候（约 1-3 分钟）...
    echo.
    %PYTHON% -m venv .venv
    if not exist ".venv\Scripts\activate.bat" (
        echo [错误] 创建虚拟环境失败，尝试用系统 Python 直接运行...
        %PYTHON% -m pip install -r requirements.txt --quiet
        %PYTHON% main.py %*
        pause
        exit /b
    )
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
    echo 依赖安装完成！
    echo.
) else (
    call .venv\Scripts\activate.bat
)

:: ---- 运行主程序 ----
echo 正在运行程序...
echo.
python main.py %*

echo.
pause
