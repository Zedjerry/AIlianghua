# -*- coding: utf-8 -*-
"""
mine_factor.py — 用 AlphaMaster 的 RL 在我们自己的 A 股数据上挖因子公式
========================================================================
在导出的 parquet 上运行 AlphaMaster 强化学习搜索，挖出 A 股专属的
可解释因子公式，保存到 quant-beginner/formulas/ 供 factor_miner.py 使用。

用法:
    python mine_factor.py --symbol 600519 --steps 600      # 快速验证（约几分钟）
    python mine_factor.py --symbol 600519 --steps 9000     # 完整挖掘（CPU 上可能数小时）
    python mine_factor.py --file "D:\...\000001_daily.parquet" --steps 300   # 直接用你已有的旧数据挖
    python mine_factor.py --symbol 000001 --steps 600 --from-scratch

输出:
    formulas/{symbol}_formula.json   （factor_miner.py 读取它）
    alpha_work/checkpoints/          训练检查点（可断点续训）
"""

import argparse
import json
import os
import shutil
import sys

ALPHA_WORK = r"D:\测试\alpha_work"
FORMULA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formulas")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="600519", help="股票代码（用默认数据目录时）")
    parser.add_argument("--file", default=None,
                        help="直接指定 parquet 数据文件（优先于 --symbol）")
    parser.add_argument("--steps", type=int, default=600, help="RL 训练步数（正式用 9000）")
    parser.add_argument("--from-scratch", action="store_true", help="从头训练（清检查点）")
    args = parser.parse_args()

    os.makedirs(FORMULA_DIR, exist_ok=True)
    os.chdir(ALPHA_WORK)                 # AlphaMaster 用相对路径写 checkpoints/strategies
    sys.path.insert(0, ALPHA_WORK)

    # 覆盖训练步数
    from model_core.config import ModelConfig
    ModelConfig.TRAIN_STEPS = args.steps
    print(f"训练步数: {args.steps}", flush=True)

    from train_file import train_from_file

    if args.file:
        data_file = args.file
    else:
        data_file = os.path.join(ALPHA_WORK, "data_a", f"{args.symbol}_D1.parquet")
    if not os.path.exists(data_file):
        raise SystemExit(f"缺少数据: {data_file}，请先运行 export_alpha_data.py 或指定 --file")

    engine = train_from_file(data_file, from_scratch=args.from_scratch)
    if engine is None:
        print("[失败] 训练未产生引擎（查看上方日志）", flush=True)
        sys.exit(1)

    # 复制挖出的公式到 quant-beginner/formulas/
    src = os.path.join(ALPHA_WORK, "strategies", f"best_{args.symbol}.json")
    if os.path.exists(src):
        dst = os.path.join(FORMULA_DIR, f"{args.symbol}_formula.json")
        shutil.copy2(src, dst)
        with open(dst, "r", encoding="utf-8") as f:
            spec = json.load(f)
        print(f"\n[OK] 挖出公式已保存: {dst}", flush=True)
        print(f"    解码: {spec.get('formula_decoded', '?')}", flush=True)
        print(f"    分数: {spec.get('best_score', '?')}", flush=True)
        print("下一步: python factor_miner.py --formula <该文件> 接入特征管线", flush=True)
    else:
        print(f"[警告] 未找到策略输出: {src}（训练可能未收敛）", flush=True)


if __name__ == "__main__":
    main()
