# -*- coding: utf-8 -*-
"""
walkforward.py — 滚动样本外检验（跨年度稳健性测试）
====================================================
把 2019 年至今的历史切成若干段（每段约半年），对每段:
    只允许用「该段之前」的数据训练模型 → 在该段（模型没见过的未来）做评估
    → 记录该段的 IC 与信号超额收益 → 滚动到下一段。

这样能回答最关键的问题: "策略在不同市场环境（牛/熊/震荡）下还行不行？"
如果大部分时期 IC>0、超额>0，策略才算真正稳健；只在一两个时期赚钱 = 运气。

输出:
    output/walkforward_report.csv   每期 IC / 超额 / 胜率
    output/walkforward_chart.png    逐年表现图

用法:  python walkforward.py     （首次运行约 5~10 分钟，请耐心）
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from step6_track_signals import train_quick  # 复用回填训练函数

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = "output"
TOP_K = 20
STEP_DAYS = 126        # 每段约半年（126 个交易日）
TRAIN_MIN = 50000      # 训练样本下限
TRAIN_START = "2019-07-01"


def main():
    # ---------- 数据 ----------
    df = pd.read_csv(os.path.join("data", "features.csv"), dtype={"code": str})
    feature_cols = [c for c in df.columns if c not in ("date", "code", "label")]

    daily = pd.read_csv(os.path.join("data", "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    daily = daily.sort_values(["code", "date"])
    daily["fwd5"] = daily.groupby("code")["close"].shift(-5) / daily["close"] - 1

    idx = pd.read_csv(os.path.join("data", "index_000300.csv"))
    idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
    idx = idx.sort_values("date")
    idx["fwd5"] = idx["close"].shift(-5) / idx["close"] - 1

    labeled_dates = sorted(df[df["label"].notna()]["date"].unique())
    dates = [d for d in labeled_dates if d >= TRAIN_START]

    # ---------- 滚动检验 ----------
    print(f"滚动样本外检验: {dates[0]} ~ {dates[-1]}，每 {STEP_DAYS} 个交易日一段...", flush=True)
    rows = []
    for i in range(0, len(dates), STEP_DAYS):
        eval_start = dates[i]
        eval_end = dates[min(i + STEP_DAYS, len(dates)) - 1]

        train_df = df[(df["date"] < eval_start) & df["label"].notna()]
        if len(train_df) < TRAIN_MIN:
            continue
        model = train_quick(train_df, feature_cols, num_boost_round=200)

        seg = df[(df["date"] >= eval_start) & (df["date"] <= eval_end)].copy()
        if seg.empty:
            continue
        seg["pred"] = model.predict(seg[feature_cols])

        # 段内 IC（预测与未来5日收益的相关性）
        ic = np.corrcoef(seg["pred"], seg["label"])[0, 1]

        # 段内"每5日取Top20"的超额收益与胜率
        excesses = []
        seg_dates = sorted(seg["date"].unique())
        for d in seg_dates[::5]:
            day = seg[seg["date"] == d]
            top = day.nlargest(TOP_K, "pred")["code"]
            real = daily[(daily["date"] == d) & (daily["code"].isin(top))]["fwd5"].mean()
            b = idx[idx["date"] == d]["fwd5"]
            if pd.notna(real) and len(b):
                excesses.append(real - float(b.iloc[0]))

        if excesses:
            rows.append({
                "评估期": f"{eval_start} ~ {eval_end}",
                "IC": ic,
                "平均超额(5日)": np.mean(excesses),
                "跑赢胜率": np.mean([e > 0 for e in excesses]),
                "信号次数": len(excesses),
            })
            print(f"  {eval_start} ~ {eval_end}  IC {ic:+.3f}  "
                  f"超额 {np.mean(excesses):+.2%}  胜率 {np.mean([e>0 for e in excesses]):.0%}",
                  flush=True)

    if not rows:
        raise SystemExit("没有产生任何评估段，请检查数据")

    rep = pd.DataFrame(rows)
    rep.to_csv(os.path.join(OUTPUT_DIR, "walkforward_report.csv"),
               index=False, encoding="utf-8-sig")

    # ---------- 总结 ----------
    print("\n========== 滚动检验总结 ==========")
    print(f"  共评估 {len(rep)} 个时期（每期约半年）")
    print(f"  平均 IC:        {rep['IC'].mean():+.3f}（正值占比 {100*(rep['IC']>0).mean():.0f}%）")
    print(f"  平均超额(5日):  {rep['平均超额(5日)'].mean():+.2%}")
    print(f"  跑赢胜率:       {rep['跑赢胜率'].mean():.0%}")
    pos = (rep["IC"] > 0).mean()
    if pos >= 0.7:
        print("  结论: 多数时期 IC 为正，策略跨环境稳健性较好")
    elif pos >= 0.5:
        print("  结论: 约半数时期有效，稳健性一般，实盘需谨慎")
    else:
        print("  结论: 多数时期无效，策略可能只适合特定行情，不建议实盘")

    # ---------- 图表 ----------
    fig, ax = plt.subplots(figsize=(13, 4.5))
    colors = ["#ef4444" if v > 0 else "#10b981" for v in rep["IC"]]
    ax.bar(range(len(rep)), rep["IC"], color=colors, label="IC")
    ax.axhline(0, color="#7d8aa3", linewidth=0.8)
    ax.set_xticks(range(len(rep)))
    ax.set_xticklabels([f"{s[:4]}年{int(s[5:7])}月" for s in rep["评估期"]],
                       rotation=0, fontsize=8)
    ax.set_title("滚动样本外 IC（每段约半年，模型只用段前数据训练）", color="#e2e8f0")
    ax.set_ylabel("IC（预测与未来5日收益的相关系数）", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "walkforward_chart.png"), dpi=120)
    print(f"\n[OK] 明细表: {os.path.join(OUTPUT_DIR, 'walkforward_report.csv')}")
    print(f"[OK] 图表:   {os.path.join(OUTPUT_DIR, 'walkforward_chart.png')}")


if __name__ == "__main__":
    main()
