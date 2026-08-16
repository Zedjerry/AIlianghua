@echo off
rem ============================================================
rem  AI 量化系统 - 一键启动器(软件入口)
rem  双击本文件 -> 自动启动系统并打开浏览器界面
rem  关闭本窗口 = 关闭系统(数据全部保留)
rem ============================================================
chcp 936 >nul 2>&1
title AI 量化系统
cd /d "%~dp0"

set PY=D:\Python\python.exe
if not exist "%PY%" (
    echo [ERROR] 找不到 Python: %PY%
    pause
    exit /b 1
)

echo ============================================
echo    AI 量化系统 - 启动中...
echo    (浏览器将自动打开 http://127.0.0.1:8000)
echo    关闭本窗口即可退出系统
echo ============================================

if not exist "%USERPROFILE%\Desktop\AI量化系统.lnk" (
    powershell -NoProfile -Command "=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\AI量化系统.lnk');.TargetPath='%~f0';.WorkingDirectory='%~dp0';.Description='AI 量化系统';.Save()" >nul 2>&1
)

"%PY%" -u webui.py --port 8000 --open
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
    echo [ERROR] 系统异常退出(代码 %RC%), 请截图此窗口发送给开发者。
) else (
    echo [INFO] 系统已退出。
)
pause