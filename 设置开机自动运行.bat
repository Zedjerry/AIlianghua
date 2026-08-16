@echo off
rem ============================================================
rem  开机自动运行 - 一键注册
rem  方式1: 计划任务(ONLOGON)  -> 被权限拒绝时自动切换
rem  方式2: 启动文件夹(隐藏窗口) -> 免权限，绝大多数情况可用
rem  效果: 每次登录电脑后自动执行每日流程(延迟60秒等网络)
rem ============================================================
chcp 936 >nul 2>&1
cd /d "%~dp0"

set PY=D:\Python\python.exe
if not exist "%PY%" (
    echo [ERROR] 找不到 Python: %PY%
    pause
    exit /b 1
)

set REG_OK=0

schtasks /Create /TN "AIQuantDaily" /TR "\"%~dp0开机自动运行_每日流程.bat\"" /SC ONLOGON /F >nul 2>&1
if not errorlevel 1 set REG_OK=1

if not "%REG_OK%"=="1" (
    echo [提示] 计划任务被拒绝，改用启动文件夹方式...
    > "%~dp0开机自动运行_每日流程.vbs" echo Set sh = CreateObject("WScript.Shell"^)
    >> "%~dp0开机自动运行_每日流程.vbs" echo sh.Run "%~dp0开机自动运行_每日流程.bat", 0, False
    powershell -NoProfile -Command "=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\AI量化每日流程.lnk');.TargetPath='C:\Windows\System32\wscript.exe';.Arguments='\"%~dp0开机自动运行_每日流程.vbs\"';.Save()" >nul 2>&1
    if not errorlevel 1 set REG_OK=2
)

echo.
if "%REG_OK%"=="1" (
    echo [完成] 方式1已注册: 每次登录自动运行每日流程
    echo        取消: schtasks /Delete /TN AIQuantDaily /F
)
if "%REG_OK%"=="2" (
    echo [完成] 方式2已注册: 每次登录自动运行每日流程，隐藏窗口
    echo        取消: 删除启动文件夹里的 AI量化每日流程.lnk
)
if "%REG_OK%"=="0" (
    echo [失败] 两种方式都被系统拒绝。
    echo        请右键本文件，选择 以管理员身份运行 重试。
)
pause