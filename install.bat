@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title laya-opencv - Install

set "PY="
if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
if defined PY goto run

for %%V in (3.12 3.11 3.13 3.10 3.14) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if defined PY goto run

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if defined PY goto run

echo.
echo [!] Python 3.10 or newer was not found.
echo [!] 没有找到 Python 3.10 或更高版本。
echo.
where winget >nul 2>&1
if errorlevel 1 goto manual
choice /c YN /m "Install Python 3.12 with winget now? / 现在用 winget 安装 Python 3.12 吗"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PY="%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PY goto run
if exist "%ProgramFiles%\Python312\python.exe" set PY="%ProgramFiles%\Python312\python.exe"
if defined PY goto run
echo.
echo Python is installed, but this window cannot see it yet. Close it and run install.bat again.
echo Python 已安装，但当前窗口还找不到它。请关闭这个窗口，重新双击 install.bat。
goto end

:manual
echo Install Python 3.12 first, tick "Add python.exe to PATH", then run install.bat again:
echo 请先安装 Python 3.12，安装时勾选 "Add python.exe to PATH"，然后重新双击 install.bat：
echo     https://www.python.org/downloads/windows/
goto end

:run
%PY% "app\install.py"
if errorlevel 1 goto failed
goto end

:failed
echo.
echo [!] Installation did not finish. Fix the error above and run install.bat again; finished steps are skipped.
echo [!] 安装没有完成。修复上面的报错后重新双击 install.bat，已完成的步骤会自动跳过。

:end
echo.
pause
