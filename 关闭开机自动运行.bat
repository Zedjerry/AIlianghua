@echo off
rem ============================================================
rem  关闭开机自动运行 - 一键取消
rem  删除: 计划任务 AIQuantDaily + 启动文件夹快捷方式
rem  如提示拒绝访问，请右键本文件 -> 以管理员身份运行
rem ============================================================
chcp 936 >nul 2>&1
cd /d "%~dp0"

echo [1/3] 删除计划任务 AIQuantDaily ...
schtasks /Delete /TN "AIQuantDaily" /F

echo [2/3] 删除启动文件夹快捷方式 ...
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
if exist "%STARTUP%\AI量化每日流程.lnk" (
    del "%STARTUP%\AI量化每日流程.lnk"
    echo       已删除快捷方式
) else (
    echo       未找到快捷方式(可能本来就没有)
)

echo [3/3] 清理隐藏运行器 ...
if exist "%~dp0开机自动运行_每日流程.vbs" (
    del "%~dp0开机自动运行_每日流程.vbs"
    echo       已删除 vbs
)

echo.
echo [完成] 开机自动运行已关闭。
echo        以后想恢复: 双击"设置开机自动运行.bat"重新注册
pause