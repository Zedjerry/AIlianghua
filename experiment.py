# -*- coding: utf-8 -*-
"""
experiment.py — 参数敏感性实验（过拟合预警工具）
================================================
对策略的关键参数做网格扫描，看收益/回撤对参数敏不敏感。

为什么重要:
    一个健康的策略应该对参数"不敏感"——TOP_K 从 15 改成 25、换仓频率
    从 5 日改成 10 日，结果不应天翻地覆。如果换个参数就从大赚变巨亏，
    说明策略在"过拟合历史"，实盘大概率翻车。

本实验扫描:
    TOP_K（持仓数）: 10 / 20 / 30
    换仓间隔(日):    5 / 10
    （预测周期固定为5日，与模型训练一致）

用法:
    python experiment.py

输出:
    output/experiment_report.csv   各参数组合的绩效对比表
    output/experiment_chart.png    年化收益对比图
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# 复用 step4 的回测引擎（不改动它，只临时改它的参数）
import step4_backtest as s4

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = "output"
TOP_K_GRID = [10, 20, 30]
REBAL_GRID = [5, 10]


def main():
    pred_file = os.path.join(OUTPUT_DIR, "test_predictions.csv")
    if not os.path.exists(pred_file):
        raise SystemExit("找不到 output/test_predictions.csv，请先运行: python run_all.py 或 python step3_train_model.py")

    pred = pd.read_csv(pred_file, dtype={"code": str})
    test_dates = sorted(pred["date"].unique())
    daily = s4.load_daily_returns(test_dates)

    print(f"扫描参数: 持仓数 {TOP_K_GRID} × 换仓间隔 {REBAL_GRID}，共 {len(TOP_K_GRID) * len(REBAL_GRID)} 组...")
    rows = []
    for topk in TOP_K_GRID:
        for rebal in REBAL_GRID:
            # 临时覆盖 step4 的全局参数（不动源文件）
            s4.TOP_K = topk
            s4.REBAL_INTERVAL = rebal
            pf = s4.run_backtest(pred, daily)
            m = s4.compute_metrics(pf)
            rows.append({
                "持仓数": topk,
                "换仓间隔(日)": rebal,
                "年化收益": m["年化收益"],
                "最大回撤": m["最大回撤"],
                "夏普比率": m["夏普比率"],
                "累计收益": m["累计收益"],
                "日胜率": m["日胜率"],
            })
            print(f"  TOP_K={topk:>2} 换仓={rebal:>2}日 -> 年化 {m['年化收益']:+.1%} "
                  f"回撤 {m['最大回撤']:.1%} 夏普 {m['夏普比率']:.2f}", flush=True)

    rep = pd.DataFrame(rows).sort_values("夏普比率", ascending=False)
    rep.to_csv(os.path.join(OUTPUT_DIR, "experiment_report.csv"),
               index=False, encoding="utf-8-sig")

    # ---------- 结论 ----------
    best = rep.iloc[0]
    worst = rep.iloc[-1]
    spread = best["年化收益"] - worst["年化收益"]
    print("\n========== 参数敏感性结论 ==========")
    print(f"  最优组合: 持仓{best['持仓数']}只/换仓{best['换仓间隔(日)']}日 (年化 {best['年化收益']:+.1%})")
    print(f"  最差组合: 持仓{worst['持仓数']}只/换仓{worst['换仓间隔(日)']}日 (年化 {worst['年化收益']:+.1%})")
    print(f"  最好与最差年化差距: {spread:.1%}")
    if spread > 0.5:
        print("  结论: 策略对参数【高度敏感】——过拟合风险高，实盘前必须谨慎，建议简化参数或加约束")
    elif spread > 0.2:
        print("  结论: 策略对参数【中度敏感】——可接受但需固定参数并持续监控")
    else:
        print("  结论: 策略对参数【较稳健】——过拟合风险相对低，但仍需向前验证")

    # ---------- 图表 ----------
    fig, ax = plt.subplots(figsize=(10, 4.5))
    labels = [f"K{r['持仓数']}·{r['换仓间隔(日)']}d" for _, r in rep.iterrows()]
    vals = rep["年化收益"]
    colors = ["#27ae60" if v >= 0 else "#c0392b" for v in vals]
    ax.bar(labels, vals, color=colors)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_title("参数敏感性: 各组合年化收益")
    ax.set_ylabel("年化收益"); ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=30, fontsize=8); plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "experiment_chart.png"), dpi=120)
    print(f"\n[OK] 对比表: {os.path.join(OUTPUT_DIR, 'experiment_report.csv')}")
    print(f"[OK] 对比图: {os.path.join(OUTPUT_DIR, 'experiment_chart.png')}")


if __name__ == "__main__":
    main()
