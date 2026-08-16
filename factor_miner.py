# -*- coding: utf-8 -*-
"""
factor_miner.py — AlphaMaster 因子挖掘中心适配器
================================================
把「基于深度神经网络强化学习的量化因子挖掘中心」(AlphaMaster) 的因子公式引擎
接入我们的 A 股量化系统：

    ① 用 AlphaMaster 的 MT5FeatureEngineer 从我们的沪深300 日线数据算 30 个特征
    ② 用 StackVM 执行 RL 挖掘出的因子公式（strategies/*.json）
    ③ 得到 [股票数, 时间] 的横截面因子（自动 z-score 归一化）
    ④ 存成 data/extra_factors_am.csv，供 step2 合并进特征管线

用法:
    python factor_miner.py                                # 用默认公式(best_AAPL.json)
    python factor_miner.py --formula "D:\\量化\\AlphaMaster\\strategies\\best_AAPL.json"

之后运行:
    python step2_build_features.py   # 自动合并新因子
    python step3_train_model.py      # 重训模型看 IC 变化
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import torch

# AlphaMaster 代码路径（只读引用它的引擎，不改动它）
ALPHA_MASTER_DIR = r"D:\量化\AlphaMaster"
if ALPHA_MASTER_DIR not in sys.path:
    sys.path.insert(0, ALPHA_MASTER_DIR)

DATA_DIR = "data"
OUTPUT = os.path.join(DATA_DIR, "extra_factors_am.csv")


def load_raw_tensors() -> dict:
    """把我们的 stock_daily 转成 AlphaMaster 引擎要的 raw_dict: {key: Tensor[N,T]}"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    codes = sorted(daily["code"].unique())
    dates = sorted(daily["date"].unique())

    # 每只股票按日期 pivot（缺失日期 ffill，保证每只都是 T 长的连续序列）
    pivots = {}
    for field in ["open", "high", "low", "close", "volume"]:
        p = daily.pivot_table(index="date", columns="code", values=field)
        p = p.reindex(dates).ffill()          # 停牌日沿用最近值
        pivots[field] = p[codes].T.values     # [N, T]

    raw = {}
    for field, arr in pivots.items():
        raw[field] = torch.from_numpy(np.ascontiguousarray(arr, dtype=np.float64)).float()
    return raw, codes, dates


def compute_factor(formula_tokens: list) -> np.ndarray:
    """执行公式，返回 [N, T] 横截面因子（NaN 置 0）"""
    from model_core.features import MT5FeatureEngineer
    from model_core.vm import StackVM

    raw, _, _ = load_raw_tensors()
    feat = MT5FeatureEngineer.compute_features(raw)   # [N, 30, T]
    vm = StackVM()
    result = vm.execute(formula_tokens, feat)         # [N, T] 或 None
    if result is None:
        raise RuntimeError("公式执行失败（token 与当前 vocab 不匹配？）")
    arr = result.numpy()
    return np.nan_to_num(arr, nan=0.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", default=os.path.join(ALPHA_MASTER_DIR, "strategies", "best_AAPL.json"),
                        help="AlphaMaster 策略公式 JSON 路径")
    args = parser.parse_args()

    with open(args.formula, "r", encoding="utf-8") as f:
        spec = json.load(f)
    tokens = spec["formula"]
    decoded = spec.get("formula_decoded", "?")
    print(f"公式: {decoded}", flush=True)
    print(f"Token 数: {len(tokens)} | 数据源: {spec.get('symbol', '?')}", flush=True)

    print("计算特征 [N=288, F=30, T] ...", flush=True)
    raw, codes, dates = load_raw_tensors()
    from model_core.features import MT5FeatureEngineer
    feat = MT5FeatureEngineer.compute_features(raw)
    print(f"特征张量: {tuple(feat.shape)}", flush=True)

    print("执行因子公式...", flush=True)
    from model_core.vm import StackVM
    vm = StackVM()
    factor = vm.execute(tokens, feat)
    if factor is None:
        raise SystemExit("公式执行失败，请检查 token/vocab 是否匹配")
    arr = np.nan_to_num(factor.numpy(), nan=0.0)
    print(f"因子张量: {arr.shape}", flush=True)

    # 转成 (date, code) 长表
    df = pd.DataFrame(arr.T, index=dates, columns=codes)   # [T, N]
    out = df.stack().rename("am_factor").reset_index()
    out.columns = ["date", "code", "am_factor"]
    out.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"[OK] 因子已保存: {OUTPUT}（{len(out)} 行）", flush=True)
    print("下一步: python step2_build_features.py && python step3_train_model.py", flush=True)


if __name__ == "__main__":
    main()
