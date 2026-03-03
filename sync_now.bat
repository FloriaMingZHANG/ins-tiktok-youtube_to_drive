@echo off
cd /d "%~dp0"

set "GIT=C:\Program Files\Git\cmd\git.exe"

echo Paste your GitHub Personal Access Token, then press Enter:
set /p TOKEN=

"%GIT%" push https://FloriaMingZHANG:%TOKEN%@github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive.git main
"%GIT%" push https://FloriaMingZHANG:%TOKEN%@github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive.git v0.3.0

set TOKEN=
echo Done.
pause
