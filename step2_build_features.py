# -*- coding: utf-8 -*-
"""
Step 2: 特征工程
================
把原始日线数据加工成机器学习能用的「特征 + 标签」。

做什么:
    1. 对每只股票单独计算「时间序列特征」：过去 N 日涨跌幅、均线、波动率、成交量变化等；
    2. 对每个交易日做「横截面排名特征」：这只股票今天的动量/估值在全部股票里排第几（百分位）；
    3. 打标签 label = 未来 5 个交易日的收益率（我们要预测的目标）。

输出:
    data/features.csv  （date, code, 特征..., label）

为什么要有横截面排名特征？
    选股本质是「比谁强」：我们关心某只股票在当下全市场里的相对位置，
    而不是它的绝对数值。排名特征对模型非常关键。
"""

import os

import numpy as np
import pandas as pd

DATA_DIR = "data"
OUTPUT = os.path.join(DATA_DIR, "features.csv")
EXTRA_CSV = os.path.join(DATA_DIR, "extra_factors.csv")
AM_EXTRA_CSV = os.path.join(DATA_DIR, "extra_factors_am.csv")  # AlphaMaster 挖出的因子

# 未来多少天收益作为标签（预测目标）
LABEL_HORIZON = 5

# 需要做横截面排名（每天在全市场排序）的特征
RANK_FEATURES = ["ret_5", "close_ma20", "vol_20"]

# 额外因子中"个股级"的列，做横截面排名（市场级因子直接广播即可）
PER_STOCK_RANK = ["mf_intraday", "mf_amt_ratio"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """对原始日线数据逐股票计算特征"""
    df = df.copy()
    # 保证按 股票->日期 排序，滚动计算才正确
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    g = df.groupby("code", group_keys=False)

    # ---------- 时间序列特征（每只股票内部计算） ----------
    close = df["close"]
    df["ret_1"] = g["close"].pct_change(1)                 # 过去1日收益
    df["ret_2"] = g["close"].pct_change(2)                 # 过去2日收益
    df["ret_5"] = g["close"].pct_change(5)                 # 过去5日收益
    df["ret_10"] = g["close"].pct_change(10)               # 过去10日收益
    df["ret_20"] = g["close"].pct_change(20)               # 过去20日收益

    df["ma5"] = g["close"].transform(lambda s: s.rolling(5).mean())    # 5日均线
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20).mean())  # 20日均线
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60).mean())  # 60日均线

    df["close_ma5"] = close / df["ma5"] - 1      # 收盘价偏离5日线幅度
    df["close_ma20"] = close / df["ma20"] - 1    # 收盘价偏离20日线幅度
    df["close_ma60"] = close / df["ma60"] - 1    # 收盘价偏离60日线幅度

    df["vol_20"] = g["ret_1"].transform(lambda s: s.rolling(20).std()) * np.sqrt(252)  # 20日年化波动率
    df["vol_60"] = g["ret_1"].transform(lambda s: s.rolling(60).std()) * np.sqrt(252)  # 60日年化波动率

    df["volume_ratio"] = df["volume"] / g["volume"].transform(lambda s: s.rolling(20).mean())  # 量比
    df["turn_20"] = g["turn"].transform(lambda s: s.rolling(20).mean())                       # 20日平均换手率

    # 过去20日价格区间中当前收盘的位置（0=最低, 1=最高）
    hi20 = g["high"].transform(lambda s: s.rolling(20).max())
    lo20 = g["low"].transform(lambda s: s.rolling(20).min())
    df["hl_pos20"] = (close - lo20) / (hi20 - lo20)

    # 距20日最高点的回撤幅度
    df["dist_high20"] = g["close"].transform(lambda s: s.rolling(20).max()) / close - 1

    # ---------- 标签：未来 LABEL_HORIZON 日收益 ----------
    df["label"] = g["close"].shift(-LABEL_HORIZON) / close - 1

    return df


def add_rank_features(df: pd.DataFrame) -> pd.DataFrame:
    """横截面排名：每个交易日，把特征在全市场排成百分位(0~1)"""
    for f in RANK_FEATURES:
        df[f"rank_{f}"] = df.groupby("date")[f].rank(pct=True)
    return df


def merge_extra_factors(df: pd.DataFrame) -> pd.DataFrame:
    """合并 step2b 生成的额外因子（资金流/北向/情绪），并对个股级因子做横截面排名"""
    if not os.path.exists(EXTRA_CSV):
        print("[提示] 未找到 data/extra_factors.csv，跳过额外因子（可运行 step2b_extra_factors.py 生成）")
        return df
    extra = pd.read_csv(EXTRA_CSV, dtype={"code": str})
    df = df.merge(extra, on=["date", "code"], how="left")
    # 北向资金 2024-08 起官方停止披露 → 测试期全是填充常量，会毁掉模型预测，
    # 故不进入特征（数据仍保留在 extra_factors.csv 供研究）
    df = df.drop(columns=[c for c in ["nb_net_buy", "nb_cum_net"] if c in df.columns])
    # 市场级情绪因子: 实测同日/滞后1日版本都会把模型从"选股"带偏到"择时"、
    # 显著降低样本外 IC（0.083→0.010），故不进入特征；
    # 数据仍保留在 extra_factors.csv，想实验可临时改回
    df = df.drop(columns=[c for c in
                          ["mkt_adv_ratio", "mkt_strong", "mkt_avg_ret",
                           "mkt_amount", "mkt_vol_ratio"] if c in df.columns])
    for f in PER_STOCK_RANK:
        rk = f"rank_{f}"
        if f in df.columns and rk not in df.columns:
            df[rk] = df.groupby("date")[f].rank(pct=True)
    # AlphaMaster 因子挖掘中心挖出的因子（factor_miner.py 生成）
    if os.path.exists(AM_EXTRA_CSV):
        am = pd.read_csv(AM_EXTRA_CSV, dtype={"code": str})
        df = df.merge(am, on=["date", "code"], how="left")
        if "am_factor" in df.columns:
            df["rank_am_factor"] = df.groupby("date")["am_factor"].rank(pct=True)
            print("[提示] 已合并 AlphaMaster 因子: am_factor + rank_am_factor")
    return df


def main():
    if not os.path.exists(os.path.join(DATA_DIR, "stock_daily.csv")):
        raise SystemExit("找不到 data/stock_daily.csv，请先运行: python step1_fetch_data.py")

    raw = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    print(f"读取原始数据: {len(raw)} 行, {raw['code'].nunique()} 只股票")

    df = build_features(raw)
    df = add_rank_features(df)
    df = merge_extra_factors(df)   # 资金流/北向/情绪 额外因子

    # ---------- 清洗 ----------
    # 特征列：除 date/code/label 和原始价格/成交量列外都是特征
    # （原始价格绝对数值跨股票不可比，且已由排名特征替代，不作为模型输入）
    RAW_DROP = ["open", "high", "low", "close", "volume", "amount"]
    feature_cols = [c for c in df.columns if c not in ("date", "code", "label") + tuple(RAW_DROP)]

    # 丢掉特征或标签缺失的行（上市初期/停牌导致的 NaN）
    before = len(df)
    df = df.dropna(subset=["label"]).reset_index(drop=True)
    print(f"删除无标签行: {before} -> {len(df)}")

    # 剩余特征里的 NaN 或无穷值（如某些估值缺数据、除数为0）用整列中位数填充
    df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
    df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median())

    # 日期按字符串排序即可（格式 YYYY-MM-DD）
    df = df.sort_values(["date", "code"]).reset_index(drop=True)
    # 只保存选定的特征列（原始价格列不进入模型输入）
    # float32 足够精确，文件体积减半、后续训练更快
    out = df[["date", "code", "label"] + feature_cols].copy()
    out[feature_cols] = out[feature_cols].astype("float32")
    out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    print(f"[OK] 特征表: {len(df)} 行 × {len(feature_cols)} 个特征, 已保存 {OUTPUT}")
    print(f"   特征列表: {feature_cols}")
    print("[完成] Step 2 完成！下一步运行: python step3_train_model.py")


if __name__ == "__main__":
    main()
