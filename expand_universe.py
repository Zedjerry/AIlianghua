# -*- coding: utf-8 -*-
"""
expand_universe.py — 股票池扩容到全市场 A 股
============================================
把 D:\\量化\\数据\\A股数据 (1)\\parquet 里的 4272 只股票日线并入我们的数据库：
    ① 旧数据（1991~2026-07）转成我们的格式（成交额=收盘价×成交量估算）
    ② 新浪补最近 5 周（2026-07-08 至今）的真实数据
    ③ 全市场代码+名称表

用法:
    python expand_universe.py                 # 全流程（补数据约30-40分钟，建议后台跑）
    python expand_universe.py --skip-catchup  # 只用旧数据（快，但不含最近5周）
    python expand_universe.py --stocks 600100 002594   # 只处理指定股票（测试用）

输出:
    data/stock_daily.csv   全市场日线（约4272只）
    data/stock_list.csv    全市场代码+名称
"""

import argparse
import glob
import os
import socket
import time
from datetime import datetime

import akshare as ak
import pandas as pd

# 关键: 全局 socket 超时。akshare 内部请求不带 timeout，
# 某只股票连接挂起会导致整个扩容无限等待。15秒无响应即放弃该只。
socket.setdefaulttimeout(15)

DATA_DIR = "data"
OLD_DIR = r"D:\量化\数据\A股数据 (1)\parquet\stocks"
PROGRESS_FILE = os.path.join(DATA_DIR, "expand_progress.txt")   # 断点续传
os.makedirs(DATA_DIR, exist_ok=True)

CATCHUP_START = "2026-07-08"   # 旧数据截止次日


def ts_to_date(ts):
    """parquet 时间戳(秒/1000) -> 'YYYY-MM-DD'"""
    try:
        return datetime.fromtimestamp(ts * 1000).strftime("%Y-%m-%d")
    except Exception:
        return None


def load_old_daily(code: str) -> pd.DataFrame:
    """旧 parquet -> 我们的格式（含估算成交额）"""
    path = os.path.join(OLD_DIR, f"{code}_daily.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    df["date"] = df["time"].apply(ts_to_date)
    df = df.dropna(subset=["date"])
    df["code"] = code
    df["amount"] = df["close"] * df["tick_volume"]   # 估算成交额
    out = df[["date", "code", "open", "high", "low", "close",
              "tick_volume", "amount"]].rename(columns={"tick_volume": "volume"})
    out["turn"] = float("nan")   # 旧数据无换手率
    return out.sort_values("date").reset_index(drop=True)


def fetch_sina(code: str, start: str) -> pd.DataFrame:
    """新浪增量（start 至今），失败返回空表"""
    symbol = ("sh" if code.startswith("6") else "sz") + code
    try:
        df = ak.stock_zh_a_daily(symbol=symbol,
                                 start_date=start.replace("-", ""),
                                 end_date=time.strftime("%Y%m%d"))
        if df is None or df.empty:
            return None
        df = df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]]
        df = df.rename(columns={"turnover": "turn"})
        df["turn"] = df["turn"] * 100
        df["code"] = code
        return df
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-catchup", action="store_true", help="跳过新浪补数据")
    parser.add_argument("--stocks", nargs="*", default=None, help="只处理指定股票")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(OLD_DIR, "*_daily.parquet")))
    codes = sorted(os.path.basename(f).rsplit("_", 1)[0] for f in files)
    if args.stocks:
        codes = [c for c in args.stocks if os.path.exists(
            os.path.join(OLD_DIR, f"{c}_daily.parquet"))]
    print(f"股票数: {len(codes)}", flush=True)

    # ① 旧数据转换（快）
    print("① 转换旧数据...", flush=True)
    frames, failed = [], []
    for code in codes:
        df = load_old_daily(code)
        if df is not None:
            frames.append(df)
        else:
            failed.append(code)
    old = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["date", "code", "open", "high", "low", "close", "volume", "amount", "turn"])
    print(f"   旧数据 {len(old)} 行, {old['code'].nunique()} 只", flush=True)
    if failed:
        print(f"   转换失败 {len(failed)} 只: {failed[:10]}", flush=True)

    # ② 新浪补最近（慢，带断点续传）
    if args.skip_catchup:
        print("② 跳过新浪补数据（--skip-catchup）", flush=True)
    else:
        done_codes = set()
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                done_codes = set(x.strip() for x in f if x.strip())
            if done_codes:
                print(f"② 续传: 已抓取 {len(done_codes)} 只，跳过继续...", flush=True)
        todo = [c for c in codes if c not in done_codes]
        print(f"② 新浪补 {CATCHUP_START} 至今，剩余 {len(todo)} 只（约每只0.6秒）...", flush=True)
        fresh = []
        t0 = time.time()
        for i, code in enumerate(todo):
            df = fetch_sina(code, CATCHUP_START)
            if df is not None:
                fresh.append(df)
            with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
                f.write(code + "\n")
            if (i + 1) % 200 == 0:
                print(f"   进度 {i+1}/{len(todo)} "
                      f"({(time.time()-t0)/(i+1)*len(todo)/60:.0f}分钟预计)", flush=True)
            time.sleep(0.05)
        if fresh:
            new = pd.concat(fresh, ignore_index=True)
            # 合并: 旧数据为底，新浪覆盖重复日期（边界日优先新浪）
            old = pd.concat([old, new], ignore_index=True)
            old = old.drop_duplicates(subset=["date", "code"], keep="last")
            print(f"   新浪补齐后共 {len(old)} 行", flush=True)

    old = old.sort_values(["code", "date"]).reset_index(drop=True)
    old.to_csv(os.path.join(DATA_DIR, "stock_daily.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] 日线已保存: data/stock_daily.csv ({len(old)} 行, {old['code'].nunique()} 只)", flush=True)

    # ③ 代码+名称表
    print("③ 获取全市场股票名称...", flush=True)
    try:
        info = ak.stock_info_a_code_name()
        info = info.rename(columns={"code": "code", "name": "name"})
        info["code"] = info["code"].astype(str).str.zfill(6)
        names = info[info["code"].isin(old["code"].unique())]
    except Exception as e:
        names = pd.DataFrame({"code": sorted(old["code"].unique()), "name": ""})
        print(f"   名称获取失败({type(e).__name__})，仅用代码", flush=True)
    names.to_csv(os.path.join(DATA_DIR, "stock_list.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] 代码表已保存: data/stock_list.csv ({len(names)} 只)", flush=True)
    print("下一步: python step2_build_features.py && python step3_train_model.py", flush=True)


if __name__ == "__main__":
    main()
