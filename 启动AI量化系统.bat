@echo off
rem ============================================================
rem  AI 量化系统 - 一键启动器（软件入口）
rem  双击本文件 → 自动启动系统并打开浏览器界面
rem  关闭本窗口 = 关闭系统（不影响已保存的数据）
rem ============================================================
chcp 65001 >nul 2>&1
title AI 量化系统
cd /d "%~dp0"

rem ---- 钉死正确 Python（避免 PATH 混乱导致闪退） ----
set PY=D:\Python\python.exe
if not exist "%PY%" (
    echo [ERROR] Python not found: %PY%
    echo         Edit this file and fix the PY line.
    pause
    exit /b 1
)

echo ============================================
echo    AI 量化系统 - 启动中...
echo    (浏览器将自动打开 http://127.0.0.1:8000)
echo    关闭本窗口即可退出系统
echo ============================================

rem ---- 自动在桌面创建快捷方式（已存在则跳过） ----
if not exist "%USERPROFILE%\Desktop\AI量化系统.lnk" (
    powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\AI量化系统.lnk');$s.TargetPath='%~f0';$s.WorkingDirectory='%~dp0';$s.Description='AI 量化系统';$s.Save()" >nul 2>&1
)

"%PY%" -u webui.py --port 8000 --open
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" (
    echo [ERROR] 系统异常退出（代码 %RC%），请截图此窗口发送给开发者。
) else (
    echo [INFO] 系统已退出。
)
pause
