@echo off
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
  py -3 -m venv backend\.venv
  if errorlevel 1 goto failed
)
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto failed
backend\.venv\Scripts\python.exe backend\server.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo 启动失败。请检查 Python 3.9+、网络连接和上方错误信息。
pause
exit /b 1
