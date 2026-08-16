@echo off
rem ============================================================
rem  开机自动运行 - 一键注册
rem  效果: 每次登录电脑后自动执行每日流程(延迟60秒等网络)
rem  用法: 双击本文件注册; 取消: schtasks /Delete /TN AIQuantDaily /F
rem ============================================================
chcp 936 >nul 2>&1
cd /d "%~dp0"

set PY=D:\Python\python.exe
if not exist "%PY%" (
    echo [ERROR] 找不到 Python: %PY%
    pause
    exit /b 1
)

schtasks /Create /TN "AIQuantDaily" /TR "\"%~dp0开机自动运行_每日流程.bat\"" /SC ONLOGON /F

echo.
echo [完成] 已注册: 每次登录电脑自动运行每日流程
echo        查看: schtasks /Query /TN AIQuantDaily
echo        取消: schtasks /Delete /TN AIQuantDaily /F
pause