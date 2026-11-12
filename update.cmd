@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist ".git" goto prepare
where git.exe >nul 2>nul
if errorlevel 1 goto prepare
git remote get-url origin >nul 2>nul
if errorlevel 1 goto prepare
git pull --ff-only
if errorlevel 1 exit /b 1
:prepare
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap\install.ps1" %*
exit /b %errorlevel%
