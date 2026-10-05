@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title laya-opencv

if not exist ".venv\Scripts\python.exe" goto notinstalled
".venv\Scripts\python.exe" "app\launcher.py"
goto end

:notinstalled
echo.
echo [!] Not installed yet. Run install.bat first.
echo [!] 还没有安装。请先双击 install.bat。

:end
echo.
pause
