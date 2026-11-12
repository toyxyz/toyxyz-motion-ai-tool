@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap\install.ps1" -RuntimeOnly
if errorlevel 1 exit /b 1
"%~dp0python_embeded\python.exe" -X utf8 -u "%~dp0runtime\entry.py" doctor --engine kimodo
if errorlevel 1 goto failed
"%~dp0python_embeded\python.exe" -X utf8 -u "%~dp0runtime\entry.py" doctor --engine ardy
if errorlevel 1 goto failed
"%~dp0python_embeded\python.exe" -X utf8 -u "%~dp0runtime\entry.py" doctor --engine motionbricks
if errorlevel 1 goto failed
exit /b 0
:failed
exit /b 1
