@echo off
cd /d "%~dp0"

if exist "C:\Program Files\Git\cmd\git.exe" (
    set "GIT=C:\Program Files\Git\cmd\git.exe"
) else (
    set "GIT=git"
)

"%GIT%" add -A
"%GIT%" commit -m "v0.3.0: Windows support"
"%GIT%" push origin main

pause
