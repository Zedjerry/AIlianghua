# -*- coding: utf-8 -*-
"""
trade_qmt.py — 阶段3：QMT 自动下单模块（预览版）
================================================
把 step7 模拟盘的交易逻辑换成 QMT 真实下单。
架构上只换「执行层」：调仓决策仍由 rebalance.py 纯函数负责，
本模块负责「连接券商 → 取真实持仓/资金 → 执行订单 → 记录成交」。

两种模式:
    1. 预览模式（默认）: 用模拟盘账户状态演示完整下单流程，不需要 QMT，
       只打印订单、不真下单 —— 现在就能跑，用于熟悉流程。
    2. 实盘模式 (--live): 连接 QMT 真实下单，需要已开通 QMT/miniQMT 权限
       并安装 xtquant（随 QMT 客户端提供），流程见 docs/QMT接入指南.md。

用法:
    python trade_qmt.py                                  # 预览（推荐先跑这个）
    python trade_qmt.py --live --mini-path "D:/QMT/userdata_mini" --account "资金账号"

⚠️ 上线前必须: 模拟盘验证通过 → 小额试单 → 人工盯盘。
"""

import argparse
import json
import os
from datetime import datetime

try:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount
    from xtquant.xtconstant import STOCK_BUY, STOCK_SELL, FIX_PRICE
    XT_READY = True
except ImportError:
    XT_READY = False

import pandas as pd

from rebalance import compute_orders   # 与模拟盘共用同一套调仓决策

DATA_DIR = "data"
OUTPUT_DIR = "output"
SIGNAL_FILE = os.path.join(OUTPUT_DIR, "signals_today.csv")
TRADE_LOG = os.path.join(OUTPUT_DIR, "qmt_trade_log.csv")
ACCOUNT_FILE = os.path.join(OUTPUT_DIR, "paper_account.json")

TOP_K = 20
COST = 0.002


class QMTBroker:
    """QMT 交易通道封装（真实下单）"""

    def __init__(self, mini_path: str, account_id: str, session_id: int = 123456):
        if not XT_READY:
            raise SystemExit("未检测到 xtquant 环境，无法连接 QMT。")
        self.trader = XtQuantTrader(mini_path, session_id)
        self.account = StockAccount(account_id)

    def connect(self):
        self.trader.start()
        result = self.trader.connect()
        if result != 0:
            raise RuntimeError(f"QMT 连接失败，错误码: {result}")
        print("[OK] 已连接 QMT mini 通道")

    def get_positions(self) -> dict:
        """返回 {code: 股数}（代码统一成 6 位字符串）"""
        pos = {}
        for p in self.trader.query_stock_positions(self.account):
            if p.volume > 0:
                pos[p.stock_code.split(".")[0]] = int(p.volume)
        return pos

    def get_cash(self) -> float:
        return float(self.trader.query_stock_asset(self.account).cash)

    def place_order(self, action: str, code: str, shares: int, price: float) -> str:
        """下一条单（action: 买/卖），返回订单号"""
        direction = STOCK_BUY if action == "买" else STOCK_SELL
        stock_code = code + ".SH" if code.startswith("6") else code + ".SZ"
        # TODO: 实盘前请确认限价合理性（如按收盘价±1%），也可改用市价单
        order_id = self.trader.order_stock(
            self.account, stock_code, direction, int(shares),
            FIX_PRICE, float(price), "ai_quant_v1")
        return str(order_id)


def load_signal_and_prices():
    """读今日信号 + 最新收盘价，返回 (目标名单, 价格表)"""
    if not os.path.exists(SIGNAL_FILE):
        raise SystemExit("找不到 signals_today.csv，请先运行 step5_generate_signals.py")
    signal = pd.read_csv(SIGNAL_FILE, dtype={"code": str})
    target_codes = signal.sort_values("pred_5d_return", ascending=False)["code"].head(TOP_K).tolist()
    close = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    latest = close["date"].max()
    prices = {r.code: float(r.close) for r in close[close["date"] == latest].itertuples()}
    return target_codes, prices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="实盘模式（需 QMT 环境）")
    parser.add_argument("--mini-path", help="miniQMT 数据目录，如 D:/QMT/userdata_mini")
    parser.add_argument("--account", help="你的资金账号")
    args = parser.parse_args()

    target_codes, prices = load_signal_and_prices()

    # ---------- 取账户状态 ----------
    if args.live:
        # 实盘模式: 必须连 QMT
        if not XT_READY:
            raise SystemExit("未检测到 xtquant 环境。请先开通 QMT/miniQMT 权限并安装 xtquant，详见 docs/QMT接入指南.md。")
        if not args.mini_path or not args.account:
            raise SystemExit("实盘模式需要 --mini-path 和 --account 参数")
        broker = QMTBroker(args.mini_path, args.account)
        broker.connect()
        holdings = broker.get_positions()
        cash = broker.get_cash()
        print(f"[实盘模式] 当前持仓 {len(holdings)} 只, 可用资金 {cash:,.0f} 元")
    else:
        # 预览模式: 用模拟盘账户状态演示（不需要 QMT）
        if os.path.exists(ACCOUNT_FILE):
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                acc = json.load(f)
            holdings = acc.get("positions", {})
            cash = float(acc.get("cash", 0))
            print(f"[预览模式] 持仓来自模拟盘账户: {len(holdings)} 只, 现金 {cash:,.0f} 元")
        else:
            holdings, cash = {}, 200000.0
            print("[预览模式] 未找到模拟盘账户，按空仓 + 20万元演示")

    # ---------- 调仓决策（与模拟盘同一套逻辑） ----------
    res = compute_orders(holdings, target_codes, cash, prices,
                         top_k=TOP_K, cost=COST)
    print(f"目标名单 {len(target_codes)} 只, 共 {len(res.orders)} 条订单\n")

    # ---------- 执行 ----------
    rows = []
    for o in res.orders:
        if o.shares <= 0:
            print(f"  [跳过] {o.action} {o.code}: {o.note}")
            continue
        if args.live:
            order_id = broker.place_order(o.action, o.code, o.shares, o.price)
            print(f"  [下单] {o.action} {o.code} {o.shares}股 @ {o.price:.2f} -> 订单 {order_id}")
        else:
            print(f"  [预览] {o.action} {o.code} {o.shares}股 @ {o.price:.2f}  ({o.note})")
        rows.append({"time": datetime.now().isoformat(), "action": o.action,
                     "code": o.code, "shares": o.shares, "price": o.price,
                     "mode": "实盘" if args.live else "预览"})

    if rows:
        pd.DataFrame(rows).to_csv(TRADE_LOG, index=False, encoding="utf-8-sig")
        print(f"\n[OK] 订单记录已保存: {TRADE_LOG}")

    if not args.live:
        print("\n[提示] 以上为预览，未产生真实交易。确认流程无误后:")
        print("       1) 开通 QMT 权限并安装 xtquant（docs/QMT接入指南.md）")
        print("       2) 加 --live --mini-path ... --account ... 执行真实下单")
        print("       3) 务必先小额试单 + 人工盯盘！")


if __name__ == "__main__":
    main()
