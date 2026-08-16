@echo off
rem ============================================================
rem  设置每日自动交易 - 一键注册
rem  效果: 工作日16:40自动运行(收盘后): 真实数据更新 -> 信号
rem        -> 模拟盘 -> LLM诊断 -> 看板(隐藏窗口, 不打扰)
rem  电脑关机错过 -> 下次开机自动补跑
rem  取消: 双击"关闭开机自动运行.bat"
rem ============================================================
chcp 936 >nul 2>&1
cd /d "%~dp0"

set PY=D:\Python\python.exe
if not exist "%PY%" (
    echo [ERROR] 找不到 Python: %PY%
    pause
    exit /b 1
)

echo [1/2] 生成隐藏执行器...
> "%~dp0每日自动交易_执行.vbs" echo Set sh = CreateObject("WScript.Shell")
>> "%~dp0每日自动交易_执行.vbs" echo sh.Run "%~dp0每日自动交易_后台.bat", 0, False

echo [2/2] 注册计划任务(工作日16:40, 错过补跑)...
powershell -NoProfile -Command "=New-ScheduledTaskAction -Execute wscript.exe -Argument '\"%~dp0每日自动交易_执行.vbs\"';=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 16:40;=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4);Register-ScheduledTask -TaskName AIQuantDaily -Action  -Trigger  -Settings  -Force"

echo.
if errorlevel 1 (
    echo [失败] 注册被拒绝，请右键本文件 -> 以管理员身份运行 重试
) else (
    echo [完成] 已注册: 工作日16:40自动模拟交易(隐藏后台运行)
    echo        错过补跑: 下次开机自动执行
    echo        取消: 双击 关闭开机自动运行.bat
)
pause