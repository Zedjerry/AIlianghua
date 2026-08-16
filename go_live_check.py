# -*- coding: utf-8 -*-
"""
go_live_check.py — 实盘上线检查（GO / NO-GO 报告）
==================================================
把「能不能实盘」从拍脑袋变成量化判断。逐项检查实盘前的硬性条件，
全部通过输出 GO，否则输出 NO-GO 并说明缺什么。

检查项:
    1. 环境    依赖库齐全
    2. 数据    行情数据新鲜（≤10天）
    3. 模拟盘  账户存在、净值正常、未触发清仓
    4. 信号评估 已有评估记录，胜率>60% 且平均超额>0（并确认是"向前验证"而非回填）
    5. 告警    告警日志可写（风控留痕能力）
    6. QMT    xtquant 环境可用（开通 QMT 后才会通过）

用法:
    python go_live_check.py

退出码: 0 = GO（可考虑实盘，仍需小额试单）; 1 = NO-GO
"""

import os
import sys
from datetime import datetime

import pandas as pd

MIN_EVAL_ROWS = 8        # 至少评估期数
WIN_RATE = 0.60          # 胜率门槛
EXCESS = 0.0             # 平均超额门槛

REPORT = []  # (项目, 是否通过, 说明)


def item(name: str, ok: bool, note: str = ""):
    REPORT.append((name, ok, note))
    mark = "[通过]" if ok else "[未通过]"
    print(f"  {mark} {name}" + (f"  <- {note}" if note else ""))


def main():
    print("===== 实盘上线检查 =====\n")

    # 1) 环境
    try:
        import lightgbm, akshare, matplotlib  # noqa
        item("环境依赖", True)
    except ImportError as e:
        item("环境依赖", False, f"缺少 {e.name}，先 pip install")

    # 2) 数据新鲜度
    if os.path.exists("data/stock_daily.csv"):
        latest = pd.to_datetime(pd.read_csv("data/stock_daily.csv", usecols=["date"])["date"].max())
        days = (datetime.now() - latest).days
        item("数据新鲜", days <= 10, f"最新 {latest.date()}（{days} 天前）")
    else:
        item("数据新鲜", False, "缺少 data/stock_daily.csv")

    # 3) 模拟盘
    if os.path.exists("output/paper_account.json"):
        import json
        with open("output/paper_account.json", "r", encoding="utf-8") as f:
            acc = json.load(f)
        equity = float(acc.get("equity", 0))
        liquidate = acc.get("liquidate", False)
        item("模拟盘正常", equity > 0 and not liquidate,
             f"净值 {equity:,.0f} 元" + ("，但处于清仓状态！" if liquidate else ""))
    else:
        item("模拟盘正常", False, "先运行 step7 建立模拟盘")

    # 4) 信号评估（核心！只认"向前验证"数据，回填的样本内数据不算数）
    if os.path.exists("output/signal_evaluation.csv"):
        ev = pd.read_csv("output/signal_evaluation.csv")
        if "来源" in ev.columns:
            fwd = ev[ev["来源"] == "forward"]
            bfill = ev[ev["来源"] != "forward"]
            n = len(fwd)
            win = (fwd["超额收益"] > 0).mean() if n else 0.0
            excess = fwd["超额收益"].mean() if n else 0.0
            note = (f"向前验证 {n} 期" + (f"（另有回填 {len(bfill)} 期不计入）" if len(bfill) else "")
                    + (f", 胜率 {win:.0%}, 平均超额 {excess:+.2%}" if n else ""))
        else:
            n, win, excess, note = 0, 0.0, 0.0, "评估表无来源标记，请用新版 step6 重新累积"
        ok = n >= MIN_EVAL_ROWS and win >= WIN_RATE and excess >= EXCESS
        item("信号达标(向前验证)", bool(ok), note)
        if n < MIN_EVAL_ROWS:
            print(f"    [提示] 需要至少 {MIN_EVAL_ROWS} 期向前验证数据，"
                  f"请坚持每天运行 run_daily.py 累积（目前 {n} 期）")
    else:
        item("信号达标(向前验证)", False, "没有评估数据，先运行 run_daily 累积")

    # 5) 告警可写
    try:
        from notify import alert
        alert("INFO", "go_live_check", channels=["file"])
        item("告警留痕", True)
    except Exception as e:
        item("告警留痕", False, str(e))

    # 6) QMT
    try:
        import xtquant  # noqa
        item("QMT 环境", True)
    except ImportError:
        item("QMT 环境", False, "未安装 xtquant（需要开通 QMT 后由客户端提供）")

    # 汇总
    print("\n" + "=" * 46)
    fails = [r for r in REPORT if not r[1]]
    if not fails:
        print("判定: GO（条件全部满足，可以进入小额试单阶段 trade_qmt.py --live）")
        print("     仍然建议: 首月小资金 + 每天人工盯盘。")
        sys.exit(0)
    else:
        print(f"判定: NO-GO（{len(fails)} 项未通过）")
        for name, _, note in fails:
            print(f"  - {name}: {note}")
        print("缺什么补什么，全部通过后再考虑实盘。")
        sys.exit(1)


if __name__ == "__main__":
    main()
