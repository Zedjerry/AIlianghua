# -*- coding: utf-8 -*-
"""
一键运行器：按顺序执行 Step 1 → 4。
用法: python run_all.py
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    "step1_fetch_data.py",   # 下载数据
    "step2_build_features.py",  # 特征工程
    "step3_train_model.py",  # 训练模型
    "step4_backtest.py",     # 回测
]


def main():
    for step in STEPS:
        print("\n" + "=" * 60)
        print(f"[进行中] 正在运行: {step}")
        print("=" * 60)
        result = subprocess.run([sys.executable, "-u", step], cwd=BASE_DIR)
        if result.returncode != 0:
            print(f"\n[失败] {step} 运行失败（退出码 {result.returncode}）")
            print("   请把终端里最后的报错信息发给我，我来帮你修。")
            sys.exit(1)
        print(f"[OK] {step} 完成\n")
    print("[完成] 全部 4 步跑完！打开 output/nav_curve.png 和 output/backtest_report.txt 看结果。")


if __name__ == "__main__":
    main()
