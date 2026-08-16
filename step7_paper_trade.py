# -*- coding: utf-8 -*-
"""
Step 7: 模拟盘自动执行引擎（阶段3 自动下单逻辑的预演）
====================================================
用真实历史价格模拟"程序自动交易"：
    读每日信号 → 自动调仓（卖掉不在名单里的、买入名单里的）→ 计交易成本
    → 记账（现金/持仓/净值）→ 输出模拟盘日报与净值曲线。

用法:
    python step7_paper_trade.py                   # 按信号档案从默认资金开始模拟
    python step7_paper_trade.py --capital 200000  # 指定初始资金（元）

输出:
    output/paper_account.json     模拟账户状态（现金/持仓），下次运行自动续跑
    output/paper_trade_log.csv    逐日交易与净值流水
    output/paper_nav.png          模拟盘净值 vs 沪深300 曲线

⚠️ 说明:
    - 这是【模拟盘】，不连券商、不下真实单，用于验证"调仓逻辑 + 风控"写对了；
    - 简化假设: 按信号日收盘价成交、不计涨跌停、停牌股跳过；
    - 将来接 QMT 时，把这里的"成交"换成真实下单函数即可（接口相同）。
"""

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 复用两个纯逻辑模块: 调仓决策 + 风控（模拟盘与实盘共用）
from rebalance import compute_orders
from risk_manager import RiskManager
from notify import alert

DATA_DIR = "data"
OUTPUT_DIR = "output"
HISTORY_DIR = os.path.join(OUTPUT_DIR, "signal_history")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

TOP_K = 20
COST = 0.002            # 单边交易成本 2‰（佣金+滑点）
MAX_POSITION_PCT = 0.10  # 风控：单只股票市值不超过总资产的 10%
MAX_DAILY_LOSS = 0.03    # 风控：单日亏损超过 3% 则熔断买入
MAX_DRAWDOWN = 0.15      # 风控：距高点回撤超过 15% 则清仓避险
ACCOUNT_FILE = os.path.join(OUTPUT_DIR, "paper_account.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "paper_trade_log.csv")

# 全局风控实例（规则可在这里调整）
RM = RiskManager(max_daily_loss=MAX_DAILY_LOSS, max_drawdown=MAX_DRAWDOWN,
                 max_position_pct=MAX_POSITION_PCT)


# ---------- 数据 ----------

def load_closes() -> pd.DataFrame:
    """date x code 的收盘价矩阵（模拟盘按收盘价成交/估值）"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    pivot = daily.pivot_table(index="date", columns="code", values="close")
    pivot = pivot.ffill()  # 停牌日沿用最近收盘价估值
    return pivot


def load_benchmark(start_date: str) -> pd.DataFrame:
    idx = pd.read_csv(os.path.join(DATA_DIR, "index_000300.csv"))
    idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
    idx = idx.sort_values("date").reset_index(drop=True)
    idx = idx[idx["date"] >= start_date]
    idx["bench_nav"] = idx["close"] / idx["close"].iloc[0]
    return idx


def signal_dates() -> list:
    """按日期排序的所有信号档案日期"""
    return sorted(f[:10] for f in os.listdir(HISTORY_DIR) if f.endswith("_signals.csv"))


def load_signal(date_str: str) -> list:
    path = os.path.join(HISTORY_DIR, f"{date_str}_signals.csv")
    return pd.read_csv(path, dtype={"code": str})["code"].tolist()


# ---------- 账户 ----------

def new_account(capital: float) -> dict:
    return {"start_capital": capital, "cash": capital,
            "positions": {}, "last_date": None, "equity": capital}


def load_account(capital: float) -> dict:
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print("[警告] 账户文件损坏，已重置模拟盘。", flush=True)
    return new_account(capital)


def save_account(acc: dict):
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)


# ---------- 交易 ----------

def compute_limits(closes: pd.DataFrame, date_str: str, codes) -> tuple:
    """识别当日涨停/跌停的股票。主板 ±10%，创业板/科创板 ±20%（简化规则，未含ST的5%）"""
    limit_up, limit_down = set(), set()
    if date_str not in closes.index:
        return limit_up, limit_down
    pos = closes.index.get_loc(date_str)
    if pos == 0:
        return limit_up, limit_down
    prev_date = closes.index[pos - 1]
    for code in codes:
        now, prev = closes.loc[date_str, code], closes.loc[prev_date, code]
        if pd.isna(now) or pd.isna(prev) or prev <= 0:
            continue
        ret = now / prev - 1
        limit = 0.20 if code.startswith(("300", "301", "688", "689")) else 0.10
        if ret >= limit - 0.002:      # 接近涨停价（留0.2%容差）
            limit_up.add(code)
        elif ret <= -(limit - 0.002): # 接近跌停价
            limit_down.add(code)
    return limit_up, limit_down


def execute_trades(acc: dict, date_str: str, target_codes: list, closes: pd.DataFrame,
                   top_k: int = TOP_K):
    """在 date_str 收盘执行调仓，返回当日的交易记录"""
    trades = []
    prices_s = closes.loc[date_str] if date_str in closes.index else pd.Series(dtype=float)
    prices = {c: float(v) for c, v in prices_s.items() if pd.notna(v)}

    # 风控: 清仓模式 → 卖出全部持仓
    if acc.get("liquidate", False):
        for code, shares in list(acc["positions"].items()):
            price = prices.get(code)
            proceeds = shares * price * (1 - COST) if price else 0.0
            acc["cash"] += proceeds
            acc["positions"].pop(code)
            trades.append({"date": date_str, "action": "卖", "code": code,
                           "shares": shares, "price": round(float(price), 2) if price else None,
                           "amount": round(float(proceeds), 2), "note": "清仓避险"})
        acc["last_date"] = date_str
        return trades

    # 涨跌停识别（模拟真实交易的成交限制）
    all_codes = set(acc["positions"]) | set(target_codes)
    limit_up, limit_down = compute_limits(closes, date_str, all_codes)

    # 正常调仓（含"熔断时只卖不买"）: 决策逻辑全部在 rebalance.py 纯函数里
    res = compute_orders(
        acc["positions"], target_codes, acc["cash"], prices,
        top_k=top_k, cost=COST, max_position_pct=MAX_POSITION_PCT,
        allow_buy=not acc.get("halt", False),
        block_buy=limit_up, block_sell=limit_down,
    )
    acc["positions"] = res.positions
    acc["cash"] = res.cash
    for o in res.orders:
        amount = 0.0
        if o.shares and o.price:
            amount = o.shares * o.price * (1 + COST) if o.action == "买" else o.shares * o.price * (1 - COST)
        trades.append({"date": date_str, "action": o.action, "code": o.code,
                       "shares": o.shares, "price": round(o.price, 2) if o.price else None,
                       "amount": round(float(amount), 2), "note": o.note})
    acc["last_date"] = date_str
    return trades


def mark_equity(acc: dict, date_str: str, closes: pd.DataFrame):
    """按收盘价给账户估值"""
    prices = closes.loc[date_str] if date_str in closes.index else pd.Series(dtype=float)
    pos_value = sum(shares * float(prices.get(c, 0)) for c, shares in acc["positions"].items())
    acc["equity"] = round(acc["cash"] + pos_value, 2)


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=4000.0, help="初始资金（默认4000元）")
    parser.add_argument("--topk", type=int, default=None,
                        help="目标持仓数量（默认按资金自动适配：约每1500元买1只，上限20只）")
    args = parser.parse_args()

    # 资金少自动减少持仓数，避免"每只分不到一手"而空仓
    top_k = args.topk or max(1, min(TOP_K, int(args.capital // 1500)))
    if args.topk is None:
        print(f"[提示] 资金 {args.capital:,.0f} 元 → 自动适配持仓 {top_k} 只（可用 --topk 覆盖）", flush=True)

    closes = load_closes()
    dates = signal_dates()
    if not dates:
        raise SystemExit("没有信号档案，请先运行: python step5_generate_signals.py 和 python step6_track_signals.py")

    acc = load_account(args.capital)
    if acc["last_date"]:
        # 已有账户则续跑：只处理 last_date 之后的信号日
        dates = [d for d in dates if d > acc["last_date"]]
        if not dates:
            print("模拟盘已是最新，无需处理。删除 output/paper_account.json 可重置。")
            return
    print(f"模拟盘起始: 初始资金 {acc['start_capital']:.0f} 元，处理 {len(dates)} 个信号日...")

    log_rows = []
    prev_equity = acc.get("start_capital")
    peak_equity = acc.get("peak_equity", acc.get("start_capital"))
    acc["halt"] = False
    acc["liquidate"] = False
    for d in dates:
        # 传完整信号名单，由调仓函数按"预测顺序 + 买得起"挑选，最多持有 top_k 只
        target = load_signal(d)
        trades = execute_trades(acc, d, target, closes, top_k=top_k)
        mark_equity(acc, d, closes)
        # 风控判定（risk_manager 纯函数）: 更新回撤跟踪 + 熔断/清仓开关
        peak_equity = max(peak_equity, acc["equity"])
        acc["peak_equity"] = peak_equity
        decisions = RM.check(acc["equity"], prev_equity, peak_equity, acc["cash"])
        acc["halt"] = "halt_buy" in decisions
        acc["liquidate"] = "liquidate" in decisions
        prev_equity = acc["equity"]
        # 风控告警（阶段4）: 触发时主动提醒
        if acc["halt"]:
            alert("WARN", f"{d} 触发买入熔断（只卖不买），净值 {acc['equity']}")
        if acc["liquidate"]:
            alert("CRITICAL", f"{d} 触发回撤清仓，净值 {acc['equity']}")
        for t in trades:
            log_rows.append({**t, "equity": acc["equity"]})
        # 每日净值流水
        note = f"账户净值 {acc['equity']}"
        if acc["halt"]:
            note += " | 触发买入熔断(只卖不买)"
        if acc["liquidate"]:
            note += " | 触发回撤清仓"
        log_rows.append({"date": d, "action": "净值", "code": "", "shares": "",
                         "price": "", "amount": "", "equity": acc["equity"],
                         "note": note})
        print(f"  {d}  持仓{len(acc['positions'])}只  现金{acc['cash']:.0f}  净值{acc['equity']:.0f}", flush=True)

    save_account(acc)
    pd.DataFrame(log_rows).to_csv(LOG_FILE, index=False, encoding="utf-8-sig")

    # ---------- 报告与图表 ----------
    nav_df = pd.DataFrame([r for r in log_rows if r["action"] == "净值"])
    nav_df["date"] = nav_df["date"]
    nav_df["nav"] = nav_df["equity"].astype(float) / acc["start_capital"]
    bench = load_benchmark(nav_df["date"].iloc[0])

    total_ret = nav_df["nav"].iloc[-1] - 1
    years = len(nav_df) * 5 / 252
    ann = nav_df["nav"].iloc[-1] ** (1 / years) - 1 if years > 0 else 0
    dd = (nav_df["nav"] / nav_df["nav"].cummax() - 1).min()
    rets = nav_df["nav"].pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(252 / 5) if rets.std() > 0 else 0
    bench_total = bench["bench_nav"].iloc[-1] - 1

    print("\n========== 模拟盘绩效（含 2‰ 成本） ==========")
    print(f"  初始资金: {acc['start_capital']:.0f} 元")
    print(f"  期末净值: {acc['equity']:.0f} 元")
    print(f"  累计收益: {total_ret:.2%}  |  年化: {ann:.2%}")
    print(f"  最大回撤: {dd:.2%}  |  夏普: {sharpe:.2f}")
    print(f"  同期沪深300: {bench_total:.2%}")
    print(f"  当前持仓: {len(acc['positions'])} 只")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(nav_df["date"], nav_df["nav"], label="模拟盘", linewidth=1.6)
    ax.plot(bench["date"], bench["bench_nav"], label="沪深300", linewidth=1.4, alpha=0.8)
    ax.set_title("模拟盘净值 vs 沪深300")
    ax.set_ylabel("净值（起点=1）")
    ax.legend(); ax.grid(alpha=0.3)
    plt.xticks(rotation=45, fontsize=8)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "paper_nav.png"), dpi=130)
    print(f"\n[OK] 交易流水: {LOG_FILE}")
    print(f"[OK] 净值曲线: {os.path.join(OUTPUT_DIR, 'paper_nav.png')}")
    print("[提示] 删除 output/paper_account.json 可重置模拟盘重新开始。")


if __name__ == "__main__":
    main()
