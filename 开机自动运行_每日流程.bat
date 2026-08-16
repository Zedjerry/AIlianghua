@echo off
rem ============================================================
rem  开机自动运行_每日流程（由"设置开机自动运行.bat"注册，勿直接双击）
rem  登录后延迟60秒（等网络就绪）→ 运行 run_daily.py → 日志写入文件
rem ============================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"

timeout /t 60 /nobreak >nul 2>&1

set PY=D:\Python\python.exe
if not exist "%PY%" exit /b 1

if not exist "output\daily_logs" mkdir "output\daily_logs"
"%PY%" -u run_daily.py >> "output\daily_logs\startup.log" 2>&1
exit /b 0
