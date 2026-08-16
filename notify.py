# -*- coding: utf-8 -*-
"""
notify.py — 告警通知模块（阶段4）
=================================
当系统出现异常或风控触发时，用多种渠道提醒你，不用天天盯着屏幕。

告警分级:
    INFO      日常信息（如: 每日流程完成）
    WARN      需要注意（如: 数据7天未更新、风控熔断触发）
    CRITICAL  必须处理（如: 每日流水线失败、模拟盘回撤超限）

通知渠道（可多选，默认 console + file）:
    console   控制台输出
    file      写入 output/alerts.log（可回溯）
    email     邮件（需在下面配置 SMTP，可选）
    toast     Windows 通知气泡（可选，失败自动忽略）

用法:
    from notify import alert
    alert("WARN", "风控熔断触发: 只卖不买")

独立演示:  python notify.py
"""

import os
import subprocess
import sys
from datetime import datetime

# ---------------- 邮件配置（可选） ----------------
# 想用邮件告警就填这里；不想用就留空
EMAIL_SMTP = ""      # 如 "smtp.qq.com"
EMAIL_PORT = 465
EMAIL_USER = ""      # 发件邮箱
EMAIL_PASS = ""      # 授权码（QQ/163 等用授权码，不是登录密码）
EMAIL_TO = ""        # 收件邮箱

ALERT_LOG = os.path.join("output", "alerts.log")
os.makedirs("output", exist_ok=True)

_LEVELS = ("INFO", "WARN", "CRITICAL")


# ---------------- 各渠道实现 ----------------

def _console(level: str, msg: str):
    print(f"[{level}] {datetime.now():%H:%M:%S} {msg}", flush=True)


def _file(level: str, msg: str):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [{level}] {msg}\n"
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def _email(level: str, msg: str):
    if not (EMAIL_SMTP and EMAIL_USER and EMAIL_PASS and EMAIL_TO):
        raise RuntimeError("邮件渠道未配置（notify.py 顶部的 EMAIL_* 留空）")
    import smtplib
    from email.mime.text import MIMEText
    mail = MIMEText(f"时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n级别: {level}\n内容: {msg}",
                    "plain", "utf-8")
    mail["Subject"] = f"[AI量化告警-{level}] {msg[:30]}"
    mail["From"] = EMAIL_USER
    mail["To"] = EMAIL_TO
    server = smtplib.SMTP_SSL(EMAIL_SMTP, EMAIL_PORT, timeout=15)
    server.login(EMAIL_USER, EMAIL_PASS)
    server.sendmail(EMAIL_USER, [EMAIL_TO], mail.as_string())
    server.quit()


def _toast(level: str, msg: str):
    """Windows 通知气泡（可选渠道，失败自动忽略）"""
    title = f"AI量化-{level}"
    xml = (f"<toast><visual><binding template='ToastText02'>"
           f"<text id='1'>{title}</text><text id='2'>{msg[:80]}</text>"
           f"</binding></visual></toast>")
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, "
          "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
          "$n=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AIQuant');"
          f"$t=[Windows.UI.Notifications.ToastNotification]::new('{xml}');$n.Show($t)")
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------- 对外接口 ----------------

def alert(level: str, msg: str, channels=None):
    """发一条告警。channels 如 ["console","file","email","toast"]，默认 console+file"""
    level = level.upper()
    if level not in _LEVELS:
        raise ValueError(f"未知告警级别: {level}，可选 {_LEVELS}")
    channels = channels or ["console", "file"]
    for ch in channels:
        fn = globals().get(f"_{ch}")
        if fn is None:
            print(f"[notify] 未知渠道: {ch}", flush=True)
            continue
        try:
            fn(level, msg)
        except Exception as e:
            # 单个渠道失败不影响其他渠道
            print(f"[notify] {ch} 渠道发送失败: {e}", flush=True)


def check_health() -> list:
    """健康检查: 数据新鲜度 / 今日信号 / 模拟盘账户，返回告警列表（测试用）"""
    warns = []
    # 数据新鲜度
    daily_path = os.path.join("data", "stock_daily.csv")
    if not os.path.exists(daily_path):
        warns.append(("CRITICAL", "缺少 data/stock_daily.csv，请先运行 step1"))
    else:
        import pandas as pd
        latest = pd.to_datetime(pd.read_csv(daily_path, usecols=["date"])["date"].max())
        days = (datetime.now() - latest).days
        if days > 7:
            warns.append(("WARN", f"行情数据已 {days} 天未更新"))
    # 今日信号
    sig = os.path.join("output", "signals_today.csv")
    if not os.path.exists(sig):
        warns.append(("WARN", "缺少今日信号，请运行 step5"))
    return warns


# ---------------- 独立演示 ----------------

def _demo():
    print("===== 告警模块演示 =====\n")
    alert("INFO", "每日流程完成（演示）")
    alert("WARN", "行情数据 8 天未更新（演示）")
    alert("CRITICAL", "每日流水线运行失败（演示）")
    print(f"\n告警日志已写入: {ALERT_LOG}")
    print("\n健康检查结果:")
    for level, msg in check_health():
        print(f"  [{level}] {msg}")
    if not check_health():
        print("  [OK] 一切正常")


if __name__ == "__main__":
    _demo()
