# -*- coding: utf-8 -*-
"""
selftest.py — 一键自检（验收脚本）
==================================
检查环境、数据、各模块是否正常。小白克隆仓库或换电脑后，跑一遍就知道系统状态。

用法:
    python selftest.py         # 快速自检（约10秒）
    python selftest.py --full  # 完整自检（额外跑一遍回测，约1~2分钟）

退出码: 0 = 全部通过;  1 = 有失败项（把输出发我帮你排查）
"""

import os
import subprocess
import sys
from datetime import datetime

RESULTS = []  # (名称, 是否通过, 备注)


def check(name: str, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))


# ---------- ① 环境检查 ----------

def env_check():
    import pandas, numpy, lightgbm, akshare, matplotlib  # 缺失会抛 ImportError
    print(f"    python {sys.version.split()[0]} | pandas {pandas.__version__} | "
          f"lightgbm {lightgbm.__version__} | akshare {akshare.__version__}")


# ---------- ② 数据检查 ----------

def data_check():
    for f in ["data/stock_daily.csv", "data/index_000300.csv", "data/stock_list.csv",
              "output/signals_today.csv", "output/paper_account.json"]:
        assert os.path.exists(f), f"缺少文件 {f}"
    import pandas as pd
    latest = pd.to_datetime(pd.read_csv("data/stock_daily.csv", usecols=["date"])["date"].max())
    days = (datetime.now() - latest).days
    assert days <= 10, f"行情数据已 {days} 天未更新（运行 run_daily.py 会强制刷新）"
    print(f"    行情数据最新至 {latest.date()}（{days} 天前）")


# ---------- ③ 模块自测（纯函数断言） ----------

def risk_check():
    from risk_manager import RiskManager
    rm = RiskManager()
    assert rm.check(110000, 108000, 112000, 30000) == [], "正常状态不应触发风控"
    assert rm.check(104000, 110000, 112000, 30000) == ["halt_buy"], "单日大跌应熔断买入"
    assert sorted(rm.check(88000, 90000, 112000, 30000)) == ["halt_buy", "liquidate"], "大回撤应清仓"


def rebalance_check():
    from rebalance import compute_orders
    res = compute_orders({"000001": 1000}, ["000001", "300750", "600519"],
                         100000.0, {"000001": 11.0, "300750": 180.0, "600519": 1500.0},
                         top_k=3, max_position_pct=0.5)
    assert res.positions.get("000001") == 1000, "名单内应继续持有"
    assert res.positions.get("300750") == 200, "便宜股应买入一手"
    assert "600519" not in res.positions, "一手买不起的应跳过"


def connection_check():
    from connection import with_retry, FlakyConnection
    ok = with_retry(FlakyConnection().connect, retries=5, base_delay=0.01)
    assert ok.startswith("连接成功"), "断线应自动重连成功"


def notify_check():
    from notify import alert, check_health
    alert("INFO", "selftest", channels=["file"])
    assert os.path.exists("output/alerts.log"), "告警日志应存在"
    check_health()  # 不应抛异常


def dashboard_check():
    import dashboard  # 可导入即可；完整生成由 run_daily 负责
    assert os.path.exists("output/dashboard.html"), "看板 html 应已生成"


def account_check():
    import json
    with open("output/paper_account.json", "r", encoding="utf-8") as f:
        acc = json.load(f)
    assert acc.get("equity", 0) > 0, "模拟盘净值异常"


# ---------- 主流程 ----------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="额外跑一遍回测")
    args = parser.parse_args()

    print("===== ① 环境检查 =====")
    check("依赖库可导入", env_check)

    print("\n===== ② 数据检查 =====")
    check("数据文件齐全且新鲜", data_check)

    print("\n===== ③ 模块自测 =====")
    check("风控模块", risk_check)
    check("调仓模块", rebalance_check)
    check("断线重连", connection_check)
    check("告警模块", notify_check)
    check("看板模块", dashboard_check)
    check("模拟盘账户", account_check)

    if args.full:
        print("\n===== ④ 完整回测（step4） =====")

        def backtest_check():
            base = os.path.dirname(os.path.abspath(__file__))
            r = subprocess.run([sys.executable, "-W", "ignore", "-u", "step4_backtest.py"],
                               cwd=base, stdout=subprocess.DEVNULL)
            assert r.returncode == 0, f"回测脚本退出码 {r.returncode}"

        check("回测脚本", backtest_check)

    # ---------- 汇总 ----------
    print("\n" + "=" * 46)
    print("自检结果汇总")
    print("=" * 46)
    failed = 0
    for name, ok, note in RESULTS:
        mark = "[OK]  " if ok else "[失败]"
        print(f"  {mark} {name}" + (f"  <- {note}" if note else ""))
        if not ok:
            failed += 1
    print("-" * 46)
    if failed == 0:
        print("[OK] 全部通过，系统就绪！")
    else:
        print(f"[失败] {failed} 项未通过，把上面的输出发给我帮你排查。")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
