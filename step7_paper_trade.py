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

DATA_DIR = "data"
OUTPUT_DIR = "output"
HISTORY_DIR = os.path.join(OUTPUT_DIR, "signal_history")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

TOP_K = 20
COST = 0.002            # 单边交易成本 2‰（佣金+滑点）
MAX_POSITION_PCT = 0.10  # 风控：单只股票市值不超过总资产的 10%
MAX_DAILY_LOSS = -0.03   # 风控：单日亏损超过 3% 则当日停止买入
ACCOUNT_FILE = os.path.join(OUTPUT_DIR, "paper_account.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "paper_trade_log.csv")


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

def execute_trades(acc: dict, date_str: str, target_codes: list, closes: pd.DataFrame):
    """在 date_str 收盘执行调仓，返回当日的交易记录"""
    trades = []
    prices = closes.loc[date_str] if date_str in closes.index else pd.Series(dtype=float)
    pos = acc["positions"]

    # 风控①：上一信号日触发亏损熔断 → 本日只卖不买
    halted = acc.get("halt", False)

    # 1) 卖出: 已持有但不在新名单
    for code in list(pos.keys()):
        if code not in target_codes:
            price = prices.get(code, np.nan)
            shares = pos.pop(code)
            if pd.isna(price):
                trades.append({"date": date_str, "action": "卖", "code": code,
                               "shares": shares, "price": None, "note": "无价格，按0回收"})
                acc["cash"] += 0
                continue
            proceeds = shares * price * (1 - COST)
            acc["cash"] += proceeds
            trades.append({"date": date_str, "action": "卖", "code": code,
                           "shares": shares, "price": round(float(price), 2),
                           "amount": round(float(proceeds), 2), "note": ""})

    # 2) 买入: 名单内且未持有（等权配置）
    if not halted:
        equity = acc["cash"] + sum(pos.get(c, 0) * (prices.get(c, 0)) for c in pos)
        target_value = equity / TOP_K
        for code in target_codes:
            if code in pos:
                continue
            price = prices.get(code, np.nan)
            if pd.isna(price):
                trades.append({"date": date_str, "action": "买", "code": code,
                               "shares": 0, "price": None, "amount": 0, "note": "当日无价格(停牌/未上市)，跳过"})
                continue
            # 风控②：单只市值上限
            budget = min(target_value, equity * MAX_POSITION_PCT)
            shares = int(budget / price / 100) * 100  # A股按手(100股)交易
            if shares <= 0:
                trades.append({"date": date_str, "action": "买", "code": code,
                               "shares": 0, "price": round(float(price), 2),
                               "amount": 0, "note": "资金不足一手，跳过"})
                continue
            cost = shares * price * (1 + COST)
            if cost > acc["cash"]:
                shares = int(acc["cash"] / (price * (1 + COST)) / 100) * 100
                if shares <= 0:
                    trades.append({"date": date_str, "action": "买", "code": code,
                                   "shares": 0, "price": round(float(price), 2),
                                   "amount": 0, "note": "现金不足一手，跳过"})
                    continue
                cost = shares * price * (1 + COST)
            acc["cash"] -= cost
            pos[code] = pos.get(code, 0) + shares
            trades.append({"date": date_str, "action": "买", "code": code,
                           "shares": shares, "price": round(float(price), 2),
                           "amount": round(float(cost), 2), "note": ""})

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
    parser.add_argument("--capital", type=float, default=200000.0, help="初始资金（默认20万）")
    args = parser.parse_args()

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
    acc["halt"] = False
    for d in dates:
        target = load_signal(d)
        trades = execute_trades(acc, d, target, closes)
        mark_equity(acc, d, closes)
        # 风控②：本信号日亏损超限 → 下一信号日只卖不买
        daily_ret = acc["equity"] / prev_equity - 1 if prev_equity else 0
        acc["halt"] = bool(daily_ret < MAX_DAILY_LOSS)  # 转成 Python bool，JSON 才可序列化
        prev_equity = acc["equity"]
        for t in trades:
            log_rows.append({**t, "equity": acc["equity"]})
        # 每日净值流水
        note = f"账户净值 {acc['equity']}"
        if acc["halt"]:
            note += " | 触发亏损熔断，下期只卖不买"
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
