# -*- coding: utf-8 -*-
"""
Step 6: 信号跟踪与质量评估（阶段2 模拟盘验证工具）
====================================================
自动量化第二步：把每天生成的信号【存档】，等 5 个交易日后自动核算
这批股票实际涨了多少、跑赢/跑输沪深300多少，累积成一份「信号质量报告」。

用法:
    python step6_track_signals.py              # 存档今日信号 + 评估所有已到期信号
    python step6_track_signals.py --backfill   # 额外回填最近的历史信号，立即生成战绩
    python step6_track_signals.py --backfill --start 2026-06-01  # 指定回填起始日

输出:
    output/signal_history/日期_signals.csv   每日信号存档（一份份留着）
    output/signal_evaluation.csv             累积的信号质量评估表
终端打印: 评估报告（信号平均收益 / 基准收益 / 超额 / 胜率）

⚠️ 诚实说明:
    - 回填的历史信号属于「样本内后验」，只作教学演示；
    - 真正可信的验证，是从今天开始每天运行本脚本、5日后自动核算的「向前验证」。
"""

import argparse
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import step5_generate_signals as s5

DATA_DIR = "data"
OUTPUT_DIR = "output"
HISTORY_DIR = os.path.join(OUTPUT_DIR, "signal_history")
os.makedirs(HISTORY_DIR, exist_ok=True)

TOP_K = s5.TOP_K
RAW_DROP = ["open", "high", "low", "close", "volume", "amount"]


# ---------- 工具函数 ----------

def train_quick(train_df: pd.DataFrame, feature_cols, num_boost_round=300):
    """快速训练（回填历史信号用，轮数少一点跑得快）"""
    params = {
        "objective": "regression", "metric": "l2", "learning_rate": 0.05,
        "num_leaves": 31, "max_depth": 6, "subsample": 0.8,
        "colsample_bytree": 0.8, "verbose": -1, "seed": 42,
    }
    d_train = lgb.Dataset(train_df[feature_cols], train_df["label"])
    return lgb.train(params, d_train, num_boost_round=num_boost_round)


def load_prices() -> pd.DataFrame:
    """股票日线 + 前向5日收益（fwd5），用于核算信号的实际表现"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    daily = daily.sort_values(["code", "date"])
    daily["fwd5"] = daily.groupby("code")["close"].shift(-5) / daily["close"] - 1
    return daily


def load_benchmark() -> pd.DataFrame:
    """沪深300指数 + 前向5日收益"""
    idx = pd.read_csv(os.path.join(DATA_DIR, "index_000300.csv"))
    idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
    idx = idx.sort_values("date")
    idx["fwd5"] = idx["close"].shift(-5) / idx["close"] - 1
    return idx


def record_signal(date_str: str, top_df: pd.DataFrame, source: str = "forward") -> bool:
    """把某天的 Top20 信号存档（已存在则跳过）。source: backfill(回填)/forward(向前验证)"""
    path = os.path.join(HISTORY_DIR, f"{date_str}_signals.csv")
    if os.path.exists(path):
        return False
    top_df = top_df.copy()
    top_df["source"] = source   # 标注信号来源，评估时区分样本内外
    top_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"   [已存档] {date_str} 的信号({source}) -> {os.path.basename(path)}", flush=True)
    return True


def evaluate(date_str: str, daily: pd.DataFrame, bench: pd.DataFrame):
    """核算某天信号的 5 日实际表现；数据未到期返回 None"""
    path = os.path.join(HISTORY_DIR, f"{date_str}_signals.csv")
    if not os.path.exists(path):
        return None
    sig = pd.read_csv(path, dtype={"code": str})
    rows = daily[(daily["date"] == date_str) & (daily["code"].isin(sig["code"]))]
    realized = rows["fwd5"].mean()
    if pd.isna(realized) or len(rows) == 0:
        return None  # 该日信号还看不到 5 个交易日之后的数据
    b = bench[bench["date"] == date_str]["fwd5"]
    bench_ret = float(b.iloc[0]) if len(b) else np.nan
    source = str(sig["source"].iloc[0]) if "source" in sig.columns else "backfill"  # 旧文件无标签按回填算
    return {"date": date_str, "信号5日收益": realized,
            "沪深300同期": bench_ret, "超额收益": realized - bench_ret,
            "来源": source}


def generate_signal_at(df, feature_cols, date_str: str) -> pd.DataFrame:
    """用截至 date_str 的数据训练模型，预测该日 Top20（回填历史信号用）"""
    train_df = df[(df["date"] <= date_str) & df["label"].notna()]
    if len(train_df) < 10000:
        return None
    model = train_quick(train_df, feature_cols)
    day = df[df["date"] == date_str].copy()
    day["pred_5d_return"] = model.predict(day[feature_cols])

    names = pd.read_csv(os.path.join(DATA_DIR, "stock_list.csv"), dtype={"code": str})
    close = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    last_close = close[close["date"] == date_str][["code", "close"]]

    top = day[["date", "code", "pred_5d_return"]].merge(names, on="code", how="left")
    top = top.merge(last_close, on="code", how="left")
    top = top.sort_values("pred_5d_return", ascending=False).head(TOP_K)
    top["pred_5d_return"] = top["pred_5d_return"].round(4)
    return top[["code", "name", "close", "pred_5d_return"]]


def backfill(df, feature_cols, start: str):
    """回填历史信号：从 start 起每隔5个交易日生成一次信号并存档"""
    labeled_dates = sorted(df[df["label"].notna()]["date"].unique())
    dates = [d for d in labeled_dates if d >= start][::5]
    if not dates:
        print("   [回填] 起始日期之后没有可回填的交易日")
        return
    print(f"   [回填] 将生成 {len(dates)} 天的历史信号（{dates[0]} ~ {dates[-1]}，每5日一天）...", flush=True)
    for d in dates:
        if os.path.exists(os.path.join(HISTORY_DIR, f"{d}_signals.csv")):
            continue
        top = generate_signal_at(df, feature_cols, d)
        if top is not None:
            record_signal(d, top, source="backfill")  # 回填历史信号 = 样本内


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser(description="信号跟踪与质量评估")
    parser.add_argument("--backfill", action="store_true", help="回填最近的历史信号")
    parser.add_argument("--start", default="2026-06-01", help="回填起始日期 YYYY-MM-DD")
    args = parser.parse_args()

    # ① 确保今日信号已生成并存档
    sig_file = os.path.join(OUTPUT_DIR, "signals_today.csv")
    if not os.path.exists(sig_file):
        print("还没有今日信号，先运行 step5 生成...", flush=True)
        s5.main()
    today_sig = pd.read_csv(sig_file, dtype={"code": str})
    today_date = str(today_sig["date"].iloc[0])
    record_signal(today_date, today_sig[["code", "name", "close", "pred_5d_return"]],
                  source="forward")  # 今日信号 = 向前验证

    daily = load_prices()
    bench = load_benchmark()

    # ② 可选：回填历史信号
    if args.backfill:
        print("① 计算特征（复用 step5）...", flush=True)
        df, feature_cols = s5.prepare_features(s5.get_daily()[1])
        backfill(df, feature_cols, args.start)

    # ③ 评估所有已到期信号
    print("\n② 评估已到期的信号...", flush=True)
    results = []
    for f in sorted(os.listdir(HISTORY_DIR)):
        if f.endswith("_signals.csv"):
            r = evaluate(f[:10], daily, bench)
            if r:
                results.append(r)

    if not results:
        print("   还没有可评估的信号（信号生成 5 个交易日后才能核算）。每天运行本脚本即可。", flush=True)
        return

    ev = pd.DataFrame(results).sort_values("date")
    ev.to_csv(os.path.join(OUTPUT_DIR, "signal_evaluation.csv"), index=False, encoding="utf-8-sig")

    wins = (ev["超额收益"] > 0).mean()
    n_fwd = int((ev["来源"] == "forward").sum()) if "来源" in ev.columns else 0
    n_bfill = len(ev) - n_fwd
    print(f"\n========== 信号质量评估报告（共 {len(ev)} 次信号） ==========", flush=True)
    print(f"  来源构成: 向前验证 {n_fwd} 期 + 回填 {n_bfill} 期", flush=True)
    print(f"  信号平均5日收益: {ev['信号5日收益'].mean():.2%}", flush=True)
    print(f"  沪深300同期平均: {ev['沪深300同期'].mean():.2%}", flush=True)
    print(f"  平均超额收益:   {ev['超额收益'].mean():.2%}", flush=True)
    print(f"  跑赢指数胜率:   {wins:.1%}（{int(wins * len(ev))}/{len(ev)}）", flush=True)
    print(f"  评估明细已保存: {os.path.join(OUTPUT_DIR, 'signal_evaluation.csv')}", flush=True)
    print("\n  判读标准(只认向前验证): 胜率>60% 且平均超额>0 且满8期 → 可进入阶段3", flush=True)
    print("  提醒: 回填信号属于样本内后验；请坚持每天运行本脚本做真正的向前验证。", flush=True)


if __name__ == "__main__":
    main()
