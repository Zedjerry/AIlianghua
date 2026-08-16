# -*- coding: utf-8 -*-
"""
export_alpha_data.py — 把我们的沪深300日线导出成 AlphaMaster 训练用 Parquet
==========================================================================
AlphaMaster 的 RL 因子挖掘需要单品种 K 线 parquet:
    {品种}_D1.parquet，列: time(Unix秒)/open/high/low/close/volume

用法:
    python export_alpha_data.py                       # 默认导出 5 只代表股票
    python export_alpha_data.py --symbols 600519 000001 600036 000858 601318
    python export_alpha_data.py --all                 # 全部 288 只（挖矿可换着来）
"""

import argparse
import os

import pandas as pd

DATA_DIR = "data"
ALPHA_WORK = r"D:\测试\alpha_work"
OUT_DIR = os.path.join(ALPHA_WORK, "data_a")
os.makedirs(OUT_DIR, exist_ok=True)

DEFAULT_SYMBOLS = ["600519", "000001", "600036", "000858", "601318"]  # 茅台/平安银行/招行/五粮液/中国平安


def export_symbol(daily: pd.DataFrame, code: str) -> str:
    df = daily[daily["code"] == code].sort_values("date").copy()
    if df.empty:
        return None
    df["time"] = pd.to_datetime(df["date"]).astype("int64") // 10**9  # 日期 -> Unix 秒
    out = df[["time", "open", "high", "low", "close", "volume"]].copy()
    # 清洗: 去除无效价格
    out = out[(out["close"] > 0) & (out["open"] > 0)].reset_index(drop=True)
    path = os.path.join(OUT_DIR, f"{code}_D1.parquet")
    out.to_parquet(path, index=False)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="要导出的股票代码")
    parser.add_argument("--all", action="store_true", help="导出全部股票")
    args = parser.parse_args()

    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    if args.all:
        symbols = sorted(daily["code"].unique())
    else:
        symbols = args.symbols

    done = 0
    for code in symbols:
        path = export_symbol(daily, code)
        if path:
            done += 1
            print(f"[OK] {code} -> {path}", flush=True)
        else:
            print(f"[跳过] {code} 无数据", flush=True)
    print(f"完成: {done} 只，输出目录 {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
