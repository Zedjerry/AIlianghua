# -*- coding: utf-8 -*-
"""
formula_backtest.py — 公式单票回测（AlphaMaster 最后一块功能）
==============================================================
对挖出的因子公式在个股真实行情上做 tanh 连续仓位回测：
    position = tanh(factor)，信号越强仓位越大（与 AlphaMaster 口径一致）

输出:
    output/formula_backtest_{code}.png   资金曲线 + 回撤
    output/formula_backtest_{code}.json  绩效指标

用法:
    python formula_backtest.py --formula formulas/600519_formula.json --code 600519
"""

import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

sys.path.insert(0, r"D:\测试\alpha_work")   # AlphaMaster 引擎副本
from model_core.features import MT5FeatureEngineer
from model_core.vm import StackVM

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams.update({"figure.facecolor": "#0b101d", "axes.facecolor": "#111827",
                     "axes.edgecolor": "#27304a", "axes.labelcolor": "#cbd5e1",
                     "text.color": "#e2e8f0", "xtick.color": "#7d8aa3",
                     "ytick.color": "#7d8aa3", "grid.color": "#1f2a44",
                     "savefig.facecolor": "#0b101d"})

COST = 0.0005   # 单边成本 0.05%（调仓成本，tanh 仓位变化时收取）


def run_backtest(code: str, formula_path: str) -> dict:
    spec = json.load(open(formula_path, "r", encoding="utf-8"))
    tokens = spec["formula"]
    decoded = spec.get("formula_decoded", "?")

    daily = pd.read_csv(os.path.join("data", "stock_daily.csv"), dtype={"code": str})
    d = daily[daily["code"] == code].sort_values("date").reset_index(drop=True)
    if d.empty:
        raise SystemExit(f"没有 {code} 的行情数据")

    # 单标的特征张量 [1, F, T]
    raw = {}
    for f in ["open", "high", "low", "close", "volume"]:
        raw[f] = torch.from_numpy(d[f].values.astype(np.float64)).float().unsqueeze(0)
    feat = MT5FeatureEngineer.compute_features(raw)
    vm = StackVM()
    factor = vm.execute(tokens, feat)
    if factor is None:
        raise SystemExit("公式执行失败（token/vocab 不匹配）")

    pos = torch.tanh(factor).numpy()[0]          # [T] 连续仓位 (-1,1)
    close = d["close"].values
    ret = close[1:] / close[:-1] - 1             # 每日收益
    pos_exec = pos[:-1]                          # 信号次日执行
    # 调仓成本: 起始空仓，按每步仓位变化收取
    delta = np.abs(np.diff(np.concatenate([[0.0], pos])))
    cost_penalty = COST * delta[:len(ret)]
    strat_ret = pos_exec * ret - cost_penalty
    nav = np.cumprod(1 + strat_ret)
    bench = np.cumprod(1 + ret)

    # 指标
    years = len(nav) / 252
    total = nav[-1] - 1
    ann = nav[-1] ** (1 / years) - 1 if years > 0 else 0
    sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(252) if strat_ret.std() > 0 else 0
    dd = nav / np.maximum.accumulate(nav) - 1
    max_dd = dd.min()
    win = (strat_ret > 0).mean()
    bench_total = bench[-1] - 1

    metrics = {"code": code, "date_range": f"{d['date'].iloc[0]} ~ {d['date'].iloc[-1]}",
               "bars": len(nav), "total_return": round(float(total), 4),
               "annual_return": round(float(ann), 4), "sharpe": round(float(sharpe), 3),
               "max_drawdown": round(float(max_dd), 4), "win_rate": round(float(win), 3),
               "bench_total": round(float(bench_total), 4), "decoded": decoded}

    # 图表
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(nav, label=f"因子策略(±{COST*100:.2f}%成本)", color="#ef4444", linewidth=1.4)
    axes[0].plot(bench, label="买入持有", color="#8b5cf6", linewidth=1.2, alpha=0.8)
    axes[0].set_title(f"{code} 公式单票回测: {decoded}", fontsize=10, color="#e2e8f0")
    axes[0].legend(loc="upper left", fontsize=9)
    axes[0].grid(alpha=0.3)
    axes[1].fill_between(range(len(dd)), dd * 100, 0, color="#10b981", alpha=0.5)
    axes[1].set_ylabel("回撤%", fontsize=9)
    axes[1].grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(os.path.join("output", f"formula_backtest_{code}.png"), dpi=120)
    plt.close(fig)

    with open(os.path.join("output", f"formula_backtest_{code}.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", required=True, help="公式 JSON 路径")
    parser.add_argument("--code", required=True, help="回测的股票代码")
    args = parser.parse_args()
    m = run_backtest(args.code, args.formula)
    print(json.dumps(m, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
