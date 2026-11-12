@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap\install.ps1" -RuntimeOnly
if errorlevel 1 exit /b 1
"%~dp0python_embeded\python.exe" -X utf8 -u "%~dp0runtime\entry.py" bridge %*
exit /b %errorlevel%
