# -*- coding: utf-8 -*-
"""
Step 3: 训练模型
================
用 LightGBM（梯度提升树）学习「特征 -> 未来5日收益」的规律。

核心要点（防作弊！）:
    - 按时间把数据切成 训练(前60%) / 验证(中间20%) / 测试(最后20%)，
      绝不随机打乱 —— 否则模型偷看未来，回测全是幻觉。
    - 用验证集做早停（防止过拟合），用测试集做最终评估。

输出:
    output/model.txt              训练好的模型
    output/test_predictions.csv   测试集上每天每只股票的预测值（step4 回测要用）
    output/feature_importance.txt 特征重要性排名
终端会打印: 测试集 IC / RankIC / 方向准确率
"""

import os

import lightgbm as lgb
import numpy as np
import pandas as pd

DATA_DIR = "data"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

FEATURES_CSV = os.path.join(DATA_DIR, "features.csv")

# 训练/验证/测试的时间比例
TRAIN_RATIO, VAL_RATIO = 0.6, 0.2

# 不是特征的列
META_COLS = ["date", "code", "label"]


def split_by_time(df: pd.DataFrame):
    """按日期先后切分：训练 / 验证 / 测试"""
    dates = sorted(df["date"].unique())
    n = len(dates)
    train_end = dates[int(n * TRAIN_RATIO) - 1]
    val_end = dates[int(n * (TRAIN_RATIO + VAL_RATIO)) - 1]

    train = df[df["date"] <= train_end]
    val = df[(df["date"] > train_end) & (df["date"] <= val_end)]
    test = df[df["date"] > val_end]
    print(f"时间切分: 训练 {train['date'].min()}~{train['date'].max()} "
          f"({len(train)}行) | 验证 {val['date'].min()}~{val['date'].max()} "
          f"({len(val)}行) | 测试 {test['date'].min()}~{test['date'].max()} ({len(test)}行)")
    return train, val, test


def evaluate(pred: np.ndarray, actual: np.ndarray) -> dict:
    """评估预测质量：IC(相关系数)、RankIC(秩相关系数)、方向准确率"""
    ic = np.corrcoef(pred, actual)[0, 1]
    rank_ic = np.corrcoef(pd.Series(pred).rank(), pd.Series(actual).rank())[0, 1]
    acc = np.mean((pred > 0) == (actual > 0))
    return {"IC": ic, "RankIC": rank_ic, "方向准确率": acc}


def main():
    if not os.path.exists(FEATURES_CSV):
        raise SystemExit("找不到 data/features.csv，请先运行: python step2_build_features.py")

    df = pd.read_csv(FEATURES_CSV)
    feature_cols = [c for c in df.columns if c not in META_COLS]
    print(f"读取特征表: {len(df)} 行, {len(feature_cols)} 个特征")

    train, val, test = split_by_time(df)

    X_train, y_train = train[feature_cols], train["label"]
    X_val, y_val = val[feature_cols], val["label"]
    X_test, y_test = test[feature_cols], test["label"]

    # ---------- 训练 LightGBM（带早停，防止过拟合） ----------
    params = {
        "objective": "regression",   # 回归：预测未来5日收益
        "metric": "l2",
        "learning_rate": 0.05,       # 学习率
        "num_leaves": 31,            # 树的复杂度
        "max_depth": 6,
        "subsample": 0.8,            # 行采样，增加稳健性
        "colsample_bytree": 0.8,     # 列采样
        "verbose": -1,
        "seed": 42,
    }
    d_train = lgb.Dataset(X_train, y_train)
    d_val = lgb.Dataset(X_val, y_val, reference=d_train)
    model = lgb.train(
        params, d_train,
        num_boost_round=2000,        # 上限，早停会提前结束
        valid_sets=[d_val],
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(200)],
    )
    print(f"模型训练完成，最优迭代轮数: {model.best_iteration}")

    # ---------- 测试集评估 ----------
    pred_test = model.predict(X_test)
    metrics = evaluate(pred_test, y_test.values)
    print("\n===== 测试集评估（模型没见过的最后20%时间） =====")
    for k, v in metrics.items():
        print(f"  {k}: {v:.4f}")
    print("  参考: |IC|>0.02 说明有一定预测力；IC≈0 说明模型没学到东西（需要排查）")

    # ---------- 保存预测结果（step4 回测用） ----------
    test_out = test[["date", "code", "label"]].copy()
    test_out["pred"] = pred_test
    test_out.to_csv(os.path.join(OUTPUT_DIR, "test_predictions.csv"),
                    index=False, encoding="utf-8-sig")

    # ---------- 保存模型 ----------
    model.save_model(os.path.join(OUTPUT_DIR, "model.txt"))

    # ---------- 特征重要性 ----------
    imp = pd.Series(model.feature_importance(), index=feature_cols).sort_values(ascending=False)
    imp.to_csv(os.path.join(OUTPUT_DIR, "feature_importance.txt"), header=["importance"])
    print("\n===== 特征重要性 Top 15 =====")
    print(imp.head(15).to_string())
    print("[完成] Step 3 完成！下一步运行: python step4_backtest.py")


if __name__ == "__main__":
    main()
