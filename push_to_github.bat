@echo off
cd /d "%~dp0"

set "GIT=C:\Program Files\Git\cmd\git.exe"
if not exist "%GIT%" set "GIT=git"

echo Pushing to GitHub...
"%GIT%" push origin main
"%GIT%" push origin v0.3.0

echo.
echo Done.
pause
