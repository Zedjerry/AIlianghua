# -*- coding: utf-8 -*-
"""
每日一键运行器（自动量化日常化）
================================
把三个阶段串成一条流水线，每天收盘后运行一次:
    step5 生成今日信号 → step6 存档+质量评估 → step7 模拟盘自动执行

用法:
    python run_daily.py

配合 Windows 任务计划程序可实现全自动（见 README「每日自动化」一节）。
所有日志写入 output/daily_logs/日期_时间.log，方便回溯。
"""

import datetime
import os
import subprocess
import sys

from notify import alert

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "output", "daily_logs")
os.makedirs(LOG_DIR, exist_ok=True)

STEPS = [
    "step2b_extra_factors.py",    # ⓪ 额外因子（资金流/北向/情绪，数据新则秒级跳过）
    "step5_generate_signals.py",  # ① 生成今日信号
    "step6_track_signals.py",     # ② 存档 + 信号质量评估
    "step7_paper_trade.py",       # ③ 模拟盘自动执行
    "dashboard.py",               # ④ 生成可视化看板（失败不阻断流程）
]


def main():
    log_path = os.path.join(LOG_DIR, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
    with open(log_path, "w", encoding="utf-8") as logf:
        for step in STEPS:
            print(f"[{datetime.datetime.now():%H:%M:%S}] 运行 {step} ...", flush=True)
            extra = ["--no-open"] if step == "dashboard.py" else []  # 定时任务不弹浏览器
            result = subprocess.run(
                [sys.executable, "-u", step] + extra, cwd=BASE_DIR,
                stdout=logf, stderr=subprocess.STDOUT,  # 子进程输出全部进日志文件
            )
            if result.returncode != 0:
                if step == "dashboard.py":
                    alert("WARN", "看板生成失败（不影响交易流程），请查看日志")
                    continue
                alert("CRITICAL", f"每日流水线 {step} 运行失败（退出码 {result.returncode}），请查看日志")
                print(f"[失败] {step} 退出码 {result.returncode}，完整日志: {log_path}", flush=True)
                sys.exit(1)
    alert("INFO", "每日流水线全部完成（信号+评估+模拟盘+看板）")
    print(f"[完成] 每日流程全部跑完，日志: {log_path}", flush=True)


if __name__ == "__main__":
    main()
