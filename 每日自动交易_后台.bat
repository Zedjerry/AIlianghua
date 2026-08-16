@echo off
rem 每日自动交易_后台执行(由计划任务隐藏调用, 勿直接双击)
set PY=D:\Python\python.exe
if not exist "%PY%" exit /b 1
cd /d "%~dp0"
if not exist "output\daily_logs" mkdir "output\daily_logs"
"%PY%" -u run_daily.py >> "output\daily_logs\auto.log" 2>&1
exit /b 0