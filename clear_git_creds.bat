@echo off
echo Clearing GitHub credentials...
cmdkey /delete:git:https://github.com 2>nul
cmdkey /delete:LegacyGeneric:target=git:https://github.com 2>nul
echo Done. Try push again.
pause
