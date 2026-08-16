@echo off
rem ============================================================
rem  AI量化 - 一键注册每日自动任务
rem  效果: 每个工作日 16:40 自动运行本目录下的 run_daily.py
rem        （生成信号 -> 存档评估 -> 模拟盘 -> 看板 -> 告警）
rem  用法: 双击本文件 或 在命令行执行 setup_schedule.bat
rem  管理: 查看任务  schtasks /Query /TN AIQuantDaily
rem        删除任务  schtasks /Delete /TN AIQuantDaily /F
rem ============================================================

rem 修改这里：如果 python 不在 D:\Python，先运行 where python 查实际路径
set PY=D:\Python\python.exe

if not exist "%PY%" (
    echo [错误] 找不到 %PY%
    echo        请先用 where python 查你的 python 路径，然后编辑本文件第一行。
    pause
    exit /b 1
)

schtasks /Create /TN "AIQuantDaily" /TR "%PY% -u %~dp0run_daily.py" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:40 /F

echo.
echo [完成] 已注册任务 AIQuantDaily（工作日 16:40 自动运行）
echo        查看: schtasks /Query /TN AIQuantDaily
echo        删除: schtasks /Delete /TN AIQuantDaily /F
pause
