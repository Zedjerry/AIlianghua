# -*- coding: utf-8 -*-
"""
Step 5: 每日交易信号（自动量化交易的第一步）
============================================
每天收盘后运行一次，自动完成:
    ① 下载最新行情 → ② 计算特征 → ③ 用最新数据重新训练模型 → ④ 预测 → ⑤ 输出今日买卖信号

输出:
    output/signals_today.csv   今日信号（预测未来5日涨幅最高的 Top 20 股票）
    output/latest_model.txt    用最新数据训练好的模型（每天自动更新）

⚠️ 重要说明:
    - 本脚本只生成【信号】，不会自动下单 —— 自动下单在阶段3对接券商接口后才有；
    - 请先根据信号在【模拟盘】上验证一段时间，再考虑实盘；
    - 仅供学习研究，不构成投资建议。
"""

import os
from datetime import datetime

import lightgbm as lgb
import numpy as np
import pandas as pd

import step1_fetch_data as s1
import step2_build_features as s2

DATA_DIR = "data"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

TOP_K = 20          # 每天推荐买入的数量（与 step4 回测一致）
LABEL_HORIZON = 5   # 预测未来5日收益（与 step2 一致）
RAW_DROP = ["open", "high", "low", "close", "volume", "amount"]  # 与 step2 一致


def is_data_fresh() -> bool:
    """已有行情数据是否够新——够新就跳过下载，让每日运行只要几秒。
    窗口取 2 天: 每个交易日收盘后的数据次日必更新（保证真实数据每天最新），
    周末两天内不重复下载。"""
    path = os.path.join(DATA_DIR, "stock_daily.csv")
    if not os.path.exists(path):
        return False
    latest = pd.to_datetime(pd.read_csv(path, usecols=["date"])["date"].max())
    return (datetime.now() - latest).days <= 2


def get_daily():
    """获取最新行情：数据新鲜就复用本地，否则重新下载"""
    if is_data_fresh():
        print("① 行情数据已是最新（2天内），跳过下载（交易日新数据会自动更新）", flush=True)
        stock_list = pd.read_csv(os.path.join(DATA_DIR, "stock_list.csv"), dtype={"code": str})
        daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
        return stock_list, daily
    print("① 下载最新行情数据（约2~5分钟）...", flush=True)
    stock_list = s1.fetch_stock_list()
    daily = s1.fetch_daily(stock_list["code"].tolist())
    return stock_list, daily


def prepare_features(daily: pd.DataFrame):
    """计算特征（复用 step2 的现成函数）"""
    print("② 计算特征...", flush=True)
    df = s2.build_features(daily)
    df = s2.add_rank_features(df)
    df = s2.merge_extra_factors(df)   # 资金流/北向/情绪 额外因子
    feature_cols = [c for c in df.columns if c not in ("date", "code", "label") + tuple(RAW_DROP)]

    # 无穷值/缺失值处理：只用「有标签」部分的中位数填充，避免引入未来信息
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
    median_vals = df[df["label"].notna()][feature_cols].median()
    df[feature_cols] = df[feature_cols].fillna(median_vals)

    return df.sort_values(["date", "code"]).reset_index(drop=True), feature_cols


def train_model(df: pd.DataFrame, feature_cols) -> "lgb.Booster":
    """用截至昨天为止的全部数据重新训练模型（每次运行都用最新数据）"""
    train_df = df[df["label"].notna()]  # 去掉还没有标签的最后几天
    params = {
        "objective": "regression",
        "metric": "l2",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "verbose": -1,
        "seed": 42,
    }
    d_train = lgb.Dataset(train_df[feature_cols], train_df["label"])
    model = lgb.train(params, d_train, num_boost_round=500)
    print(f"   模型训练完成: {len(train_df)} 行训练样本", flush=True)
    return model


def main():
    # ---------- ① ② 数据与特征 ----------
    stock_list, daily = get_daily()
    df, feature_cols = prepare_features(daily)
    latest_date = df["date"].max()
    print(f"   最新交易日: {latest_date}", flush=True)

    # ---------- ③ 重训模型 ----------
    print("③ 重新训练模型...", flush=True)
    model = train_model(df, feature_cols)
    model.save_model(os.path.join(OUTPUT_DIR, "latest_model.txt"))

    # ---------- ④ 预测最新一天 ----------
    today_df = df[df["date"] == latest_date].copy()
    today_df["pred_5d_return"] = model.predict(today_df[feature_cols])

    # ---------- ⑤ 输出信号 ----------
    # 注意: 内存中的特征表还保留着原始 close 列，合并前只取需要的列，避免列名冲突
    # 关联股票名称（CSV 里的代码列要按字符串读，避免被解析成整数）
    names = pd.read_csv(os.path.join(DATA_DIR, "stock_list.csv"), dtype={"code": str})
    signals = today_df[["date", "code", "pred_5d_return"]].merge(names, on="code", how="left")
    # 关联最新收盘价（仅供参考）
    close = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"),
                        usecols=["date", "code", "close"], dtype={"code": str})
    last_close = close[close["date"] == latest_date][["code", "close"]]
    signals = signals.merge(last_close, on="code", how="left")
    signals = signals.sort_values("pred_5d_return", ascending=False).reset_index(drop=True)

    top = signals.head(TOP_K).copy()
    top["pred_5d_return"] = top["pred_5d_return"].round(4)
    top.to_csv(os.path.join(OUTPUT_DIR, "signals_today.csv"), index=False, encoding="utf-8-sig")

    print(f"\n===== {latest_date} 今日信号：预测未来5日涨幅 Top {TOP_K} =====", flush=True)
    print(top[["code", "name", "close", "pred_5d_return"]].to_string(index=False), flush=True)
    print(f"\n[OK] 信号已保存: {os.path.join(OUTPUT_DIR, 'signals_today.csv')}", flush=True)
    print("[提示] 建议对照'买入持有沪深300'观察这批股票后续5日的实际表现，验证信号质量。", flush=True)
    print("[免责] 本脚本仅生成信号不自动下单，仅供学习研究，不构成投资建议。", flush=True)


if __name__ == "__main__":
    main()
