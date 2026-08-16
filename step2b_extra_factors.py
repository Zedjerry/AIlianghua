# -*- coding: utf-8 -*-
"""
Step 2b: 额外因子（资金流 / 北向资金 / 情绪指标）
==================================================
生成 data/extra_factors.csv，为每只股票每天补充三类新因子:

【北向资金】(市场级, 东财官方数据)
    nb_net_buy   当日北向净买额(亿元)
    nb_cum_net   北向历史累计净买额(亿元)
    （注: 2024-08 起官方停止披露 → 之后为缺失，自动填充中位数）

【资金流代理】(个股级, 由自有量价数据计算, 全期覆盖)
    mf_intraday   日内资金流代理 = 成交量×(收盘-开盘)/(最高-最低)，正=资金主动买入
    mf_amt_ratio  成交额 / 20日均成交额（放量/缩量）

【情绪/市场宽度】(市场级, 由自有数据计算)
    mkt_adv_ratio  当日上涨家数占比
    mkt_strong     当日涨幅≥5%的强势家数
    mkt_avg_ret    当日市场平均涨跌幅
    mkt_amount     当日市场总成交额
    mkt_vol_ratio  当日总成交额 / 20日均值（市场量能情绪）

数据源说明:
  - 北向资金市场级接口稳定（1 次请求）；个股级北向持股接口(东财)有频率限制，
    批量调用会被拒绝，故不采用 —— 个股"资金流"用 OHLCV 代理全期覆盖；
  - 数据较新时自动跳过重算（每日运行只耗时几秒）。

用法:  python step2b_extra_factors.py
"""

import os

import akshare as ak
import numpy as np
import pandas as pd

DATA_DIR = "data"
OUTPUT = os.path.join(DATA_DIR, "extra_factors.csv")


def is_extra_fresh() -> bool:
    """额外因子数据是否与行情同步（同步则跳过重算）"""
    if not os.path.exists(OUTPUT) or not os.path.exists(os.path.join(DATA_DIR, "stock_daily.csv")):
        return False
    stock_max = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), usecols=["date"])["date"].max()
    extra_max = pd.read_csv(OUTPUT, usecols=["date"])["date"].max()
    return stock_max == extra_max


# ---------- ① 北向资金（市场级） ----------

def fetch_northbound_market() -> pd.DataFrame:
    """北向资金历史: 日期 + 当日净买额 + 累计净买额"""
    df = ak.stock_hsgt_hist_em(symbol="北向资金")
    df = df[["日期", "当日成交净买额", "历史累计净买额"]].copy()
    df.columns = ["date", "nb_net_buy", "nb_cum_net"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["nb_net_buy"] = pd.to_numeric(df["nb_net_buy"], errors="coerce")
    df["nb_cum_net"] = pd.to_numeric(df["nb_cum_net"], errors="coerce") * 10000  # 万亿→亿
    print(f"[OK] 北向资金(市场级): {len(df)} 行", flush=True)
    return df[["date", "nb_net_buy", "nb_cum_net"]]


# ---------- ② 资金流代理 + 情绪宽度（自算，全期覆盖） ----------

def compute_market_and_flow(daily: pd.DataFrame) -> pd.DataFrame:
    """从自有行情数据计算市场宽度情绪 + 个股资金流代理"""
    d = daily.copy().sort_values(["code", "date"])
    d["ret_1"] = d.groupby("code")["close"].pct_change()

    # 个股资金流代理: 成交方向 = (收盘-开盘)/(最高-最低)，乘成交量
    hl = (d["high"] - d["low"]).replace(0, np.nan)
    d["mf_intraday"] = d["volume"] * (d["close"] - d["open"]) / hl
    d["mf_intraday"] = d["mf_intraday"].fillna(0.0)
    d["mf_amt_ratio"] = d["amount"] / d.groupby("code")["amount"].transform(
        lambda s: s.rolling(20).mean())

    # 市场级情绪（每天在全市场统计）
    mkt = d.groupby("date").agg(
        mkt_adv_ratio=("ret_1", lambda s: (s > 0).mean()),
        mkt_strong=("ret_1", lambda s: (s >= 0.05).sum()),
        mkt_avg_ret=("ret_1", "mean"),
        mkt_amount=("amount", "sum"),
    ).reset_index()
    mkt["mkt_vol_ratio"] = mkt["mkt_amount"] / mkt["mkt_amount"].rolling(20).mean()

    # 把市场因子广播回每行
    d = d.merge(mkt, on="date", how="left")
    return d[["date", "code", "mf_intraday", "mf_amt_ratio",
              "mkt_adv_ratio", "mkt_strong", "mkt_avg_ret", "mkt_amount", "mkt_vol_ratio"]]


def main():
    if is_extra_fresh():
        print("[OK] 额外因子已是最新，跳过（如需强制更新，删除 data/extra_factors.csv 再运行）", flush=True)
        return

    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    print(f"股票池: {len(daily['code'].unique())} 只，行情 {daily['date'].min()} ~ {daily['date'].max()}", flush=True)

    print("① 下载北向资金（市场级）...", flush=True)
    nb_mkt = fetch_northbound_market()

    print("② 计算资金流代理 + 情绪宽度...", flush=True)
    mf = compute_market_and_flow(daily)

    # 合并成 (date, code) 全矩阵
    base = daily[["date", "code"]].copy()
    out = base.merge(nb_mkt, on="date", how="left")
    out = out.merge(mf, on=["date", "code"], how="left")

    out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"[OK] 额外因子表: {len(out)} 行 × {len(out.columns)} 列, 已保存 {OUTPUT}", flush=True)
    print("    下一步运行: python step2_build_features.py（会自动合并这些因子）", flush=True)


if __name__ == "__main__":
    main()
