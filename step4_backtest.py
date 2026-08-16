# -*- coding: utf-8 -*-
"""
Step 4: 回测
============
在「模型从没见过的」测试时间段上模拟真实交易：

规则（教学版，故意做简单）:
    - 每 5 个交易日换一次仓；
    - 每次从全市场选出模型预测「未来5日收益」最高的 K=20 只股票，等权买入；
    - 每次换仓支付 0.2% 交易成本（佣金+印花税+滑点的粗略估计）；
    - 与「买入持有沪深300指数」对比。

输出:
    output/nav_curve.png        净值曲线图（策略 vs 沪深300）
    output/backtest_report.txt  绩效报告
终端打印: 年化收益 / 最大回撤 / 夏普比率 / 胜率 等
"""

import os

import matplotlib
matplotlib.use("Agg")  # 无界面环境绘图
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DATA_DIR = "data"
OUTPUT_DIR = "output"

REBAL_INTERVAL = 5   # 每5个交易日换仓
TOP_K = 20           # 每次持有预测最高的20只
COST = 0.002         # 每次换仓成本 0.2%

# 中文字体（Windows）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def load_daily_returns(test_dates) -> pd.DataFrame:
    """从原始日线数据计算每只股票每日收益率，只保留测试期"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"])
    daily = daily.sort_values(["code", "date"])
    daily["ret_1"] = daily.groupby("code")["close"].pct_change()  # 当日相对昨日的收益
    return daily[daily["date"].isin(test_dates)]


def run_backtest(pred: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """执行换仓回测，返回逐日收益表"""
    test_dates = sorted(pred["date"].unique())
    rebal_dates = test_dates[::REBAL_INTERVAL]

    # 每只股票在回测中的日收益（用于快速查询）
    ret_pivot = daily.pivot_table(index="date", columns="code", values="ret_1")

    # holdings[d] = 在日期 d 持有的股票列表
    holdings = {}
    for i, rebal in enumerate(rebal_dates):
        end = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else test_dates[-1]
        top = pred[pred["date"] == rebal].nlargest(TOP_K, "pred")["code"].tolist()
        for d in test_dates:
            if rebal < d <= end:  # 换仓日收盘买入，次日起持有
                holdings[d] = top

    rows = []
    for d in test_dates:
        r = 0.0
        codes = holdings.get(d)
        if codes:
            r = float(ret_pivot.loc[d, codes].mean(skipna=True)) if len(codes) else 0.0
        if d in rebal_dates:
            r -= COST  # 换仓日支付成本
        rows.append((d, r))

    pf = pd.DataFrame(rows, columns=["date", "pf_ret"])
    pf["nav"] = (1 + pf["pf_ret"]).cumprod()
    return pf


def compute_metrics(pf: pd.DataFrame) -> dict:
    """计算绩效指标"""
    nav = pf["nav"]
    total_ret = nav.iloc[-1] - 1
    years = len(pf) / 252
    ann_ret = nav.iloc[-1] ** (1 / years) - 1
    daily_std = pf["pf_ret"].std()
    sharpe = pf["pf_ret"].mean() / daily_std * np.sqrt(252) if daily_std > 0 else 0
    dd = nav / nav.cummax() - 1
    max_dd = dd.min()
    win_rate = (pf["pf_ret"] > 0).mean()
    return {
        "测试期天数": len(pf),
        "累计收益": total_ret,
        "年化收益": ann_ret,
        "年化波动率": daily_std * np.sqrt(252),
        "夏普比率": sharpe,
        "最大回撤": max_dd,
        "日胜率": win_rate,
    }


def normalize_date(series: pd.Series) -> pd.Series:
    """把日期列统一成 YYYY-MM-DD 字符串，兼容 20180102 / 2018-01-02 两种格式"""
    s = series.astype(str).str.strip()
    # 先按 YYYYMMDD 解析（int64 会被 pandas 误当成纳秒时间戳，必须先转字符串+指定格式）
    d = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    d = d.fillna(pd.to_datetime(s, errors="coerce"))  # 兜底：其他格式自动解析
    return d.dt.strftime("%Y-%m-%d")


def benchmark_nav(test_start: str) -> pd.DataFrame:
    """沪深300指数在测试期的净值"""
    idx = pd.read_csv(os.path.join(DATA_DIR, "index_000300.csv"))
    idx["date"] = normalize_date(idx["date"])
    idx = idx[idx["date"] >= test_start].reset_index(drop=True)
    idx["bench_ret"] = idx["close"].pct_change().fillna(0)
    idx["bench_nav"] = (1 + idx["bench_ret"]).cumprod()
    return idx


def main():
    pred_file = os.path.join(OUTPUT_DIR, "test_predictions.csv")
    if not os.path.exists(pred_file):
        raise SystemExit("找不到 output/test_predictions.csv，请先运行: python step3_train_model.py")

    pred = pd.read_csv(pred_file)
    test_dates = sorted(pred["date"].unique())
    print(f"测试期: {test_dates[0]} ~ {test_dates[-1]}，共 {len(test_dates)} 个交易日")

    daily = load_daily_returns(test_dates)
    pf = run_backtest(pred, daily)
    metrics = compute_metrics(pf)

    bench = benchmark_nav(test_dates[0])
    bench = bench[bench["date"].isin(test_dates)].reset_index(drop=True)

    # ---------- 终端报告 ----------
    print("\n===== 回测绩效（含 0.2%/次 换仓成本） =====")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    bench_total = bench["bench_nav"].iloc[-1] - 1
    print(f"\n  同期沪深300累计收益: {bench_total:.2%}")

    # ---------- 画图 ----------
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(pf["date"], pf["nav"], label="AI选股策略", linewidth=1.6)
    ax.plot(bench["date"], bench["bench_nav"], label="沪深300指数", linewidth=1.4, alpha=0.8)
    ax.set_title("AI多因子选股 vs 沪深300（测试期净值）")
    ax.set_ylabel("净值（起点=1）")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45, fontsize=8)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "nav_curve.png"), dpi=130)
    print(f"\n[OK] 净值曲线已保存: {os.path.join(OUTPUT_DIR, 'nav_curve.png')}")

    # ---------- 保存报告 ----------
    lines = ["AI 多因子选股 回测报告", "=" * 40,
             f"测试期: {test_dates[0]} ~ {test_dates[-1]}",
             f"换仓频率: 每 {REBAL_INTERVAL} 日 | 持仓数: {TOP_K} | 成本: {COST:.1%}/次", ""]
    for k, v in metrics.items():
        lines.append(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")
    lines.append(f"同期沪深300累计收益: {bench_total:.2%}")
    with open(os.path.join(OUTPUT_DIR, "backtest_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] 绩效报告已保存: {os.path.join(OUTPUT_DIR, 'backtest_report.txt')}")
    print("[完成] 全流程完成！打开 output/nav_curve.png 看图，用 output/backtest_report.txt 写总结。")


if __name__ == "__main__":
    main()
