# -*- coding: utf-8 -*-
"""
Step 1: 获取数据
================
下载「沪深300成分股」的历史日线数据（前复权），以及沪深300指数（作为对比基准）。

数据源: akshare（成分股列表走中证指数官网，行情走新浪财经接口）
注意:
    - 新浪接口偶尔也会断连，脚本内置「自动重试 + 限速」；
    - 首次运行需要联网，预计 2~5 分钟。

输出:
    data/stock_list.csv   成分股列表
    data/stock_daily.csv  所有成分股的日线数据（date, code, open, high, low, close, volume, amount, turn）
    data/index_000300.csv 沪深300指数日线（date, close）
"""

import os
import time

import akshare as ak
import pandas as pd

# ---------------- 配置 ----------------
START_DATE = "20180101"                    # 开始日期（YYYYMMDD）
END_DATE = time.strftime("%Y%m%d")         # 今天
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

MAX_RETRY = 4          # 每个请求最多重试次数
RETRY_WAIT = 3         # 重试间隔（秒）
SLEEP_BETWEEN = 0.2    # 每只股票之间的间隔（秒），避免被限流


def fetch_with_retry(fn, *args, **kwargs):
    """带重试地调用 akshare 接口（数据源偶尔断开连接）"""
    for attempt in range(1, MAX_RETRY + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRY:
                raise
            print(f"   [重试 {attempt}/{MAX_RETRY}] {type(e).__name__}，{RETRY_WAIT} 秒后重试...", flush=True)
            time.sleep(RETRY_WAIT)


def to_sina_symbol(code: str) -> str:
    """6位代码 -> 新浪格式（沪市加 sh，深市加 sz）"""
    return ("sh" if code.startswith("6") else "sz") + code


def _normalize_cons(df: pd.DataFrame) -> pd.DataFrame:
    """把各数据源返回的成分股表统一成 code/name 两列（自动识别代码列）"""
    df = df.copy()
    code_col = None
    for c in df.columns:
        # 找"绝大多数值都是6位数字"的列，即股票代码列
        if df[c].astype(str).str.fullmatch(r"\d{6}").mean() > 0.5:
            code_col = c
            break
    if code_col is None:
        raise ValueError(f"无法识别股票代码列: {list(df.columns)}")
    name_col = [c for c in df.columns if c != code_col][0]  # 剩余第一列当作名称
    out = pd.DataFrame({
        "code": df[code_col].astype(str).str.zfill(6),
        "name": df[name_col].astype(str),
    })
    return out.drop_duplicates(subset="code").reset_index(drop=True)


def fetch_stock_list() -> pd.DataFrame:
    """沪深300成分股列表（多数据源自动切换，哪个通就用哪个）"""
    sources = [
        ("新浪", ak.index_stock_cons, {"symbol": "000300"}),              # 首选：稳定快速，约288只
        ("中证指数", ak.index_stock_cons_csindex, {"symbol": "000300"}),  # 兜底：官方源300只，但接口不稳定
    ]
    last_err = None
    for name, fn, kwargs in sources:
        try:
            raw = fetch_with_retry(fn, **kwargs)
            df = _normalize_cons(raw)
            if len(df) < 200:
                # 接口偶尔会返回残缺数据（如只有1只），视为失败，切换下一个源
                raise ValueError(f"数据不完整，仅 {len(df)} 只")
            print(f"[OK] 成分股列表（{name}源）: {len(df)} 只，已保存 data/stock_list.csv", flush=True)
            df.to_csv(os.path.join(DATA_DIR, "stock_list.csv"), index=False, encoding="utf-8-sig")
            return df
        except Exception as e:
            last_err = e
            print(f"   [{name}源失败] {type(e).__name__}，自动切换下一个源...", flush=True)
    raise RuntimeError(f"所有成分股数据源都失败了，请检查网络。最后一个错误: {last_err}")


def fetch_daily(codes) -> pd.DataFrame:
    """逐只下载日线（前复权），拼成一个大表"""
    frames = []
    failed = []
    for i, code in enumerate(codes):
        try:
            df = fetch_with_retry(
                ak.stock_zh_a_daily,
                symbol=to_sina_symbol(code),
                start_date=START_DATE, end_date=END_DATE,
                adjust="qfq",   # 前复权（关键！）
            )
            df = df[["date", "open", "high", "low", "close", "volume", "amount", "turnover"]].copy()
            df = df.rename(columns={"turnover": "turn"})
            df["turn"] = df["turn"] * 100          # 新浪的换手率是小数，转成百分数
            df["code"] = code
            frames.append(df)
        except Exception as e:
            failed.append((code, type(e).__name__))
            print(f"   [跳过] {code} 多次重试仍失败: {type(e).__name__}", flush=True)
        if (i + 1) % 25 == 0:
            print(f"   已下载 {i+1}/{len(codes)}", flush=True)
        time.sleep(SLEEP_BETWEEN)

    if failed:
        print(f"   共 {len(failed)} 只股票下载失败: {[c for c, _ in failed]}", flush=True)
    if not frames:
        raise RuntimeError("没有下载到任何数据，请检查网络后重试")

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["code", "date"]).reset_index(drop=True)
    all_df.to_csv(os.path.join(DATA_DIR, "stock_daily.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] 日线数据: {len(all_df)} 行, {all_df['code'].nunique()} 只股票, 已保存 data/stock_daily.csv", flush=True)
    return all_df


def fetch_index() -> pd.DataFrame:
    """沪深300指数日线，作为回测对比基准"""
    df = fetch_with_retry(ak.stock_zh_index_daily, symbol="sh000300")
    df = df[["date", "close"]].copy()
    # 统一成 YYYY-MM-DD 字符串，与股票数据的日期格式保持一致
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    start_iso = f"{START_DATE[:4]}-{START_DATE[4:6]}-{START_DATE[6:]}"
    end_iso = f"{END_DATE[:4]}-{END_DATE[4:6]}-{END_DATE[6:]}"
    df = df[(df["date"] >= start_iso) & (df["date"] <= end_iso)]
    df.to_csv(os.path.join(DATA_DIR, "index_000300.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] 沪深300指数: {len(df)} 行, 已保存 data/index_000300.csv", flush=True)
    return df


def main():
    print("开始下载数据（首次约 2~5 分钟，请耐心等待）...", flush=True)
    stock_list = fetch_stock_list()
    fetch_daily(stock_list["code"].tolist())
    fetch_index()
    print("[完成] Step 1 完成！数据已就绪，下一步运行: python step2_build_features.py", flush=True)


if __name__ == "__main__":
    main()
