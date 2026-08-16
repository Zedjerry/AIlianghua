# -*- coding: utf-8 -*-
"""
rebuild_after_expand.py — 扩容后一键重建
========================================
股票池扩容到全市场后运行:
    step2b 额外因子(资金流/北向/情绪)  → step2 特征 → step3 重训 → step5 今日信号
全市场 4272 只，预计 30~60 分钟。

用法:  python rebuild_after_expand.py
"""

import subprocess
import sys
import time
from datetime import datetime

STEPS = [
    ("step2b_extra_factors.py", "额外因子(资金流/北向/情绪)"),
    ("step2_build_features.py", "特征工程(全市场)"),
    ("step3_train_model.py",    "重训模型(全市场,看IC)"),
    ("step5_generate_signals.py", "今日信号(全市场)"),
]


def main():
    for script, desc in STEPS:
        print(f"\n[{datetime.now():%H:%M:%S}] ===== {desc}: {script} =====", flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, "-W", "ignore", "-u", script])
        print(f"[{datetime.now():%H:%M:%S}] {script} 退出码 {r.returncode} "
              f"(耗时 {(time.time()-t0)/60:.1f} 分钟)", flush=True)
        if r.returncode != 0:
            print(f"!!! {script} 失败，流程中止。请把上面的报错发给我。", flush=True)
            sys.exit(1)
    print("\n[完成] 扩容后重建全部完成！", flush=True)


if __name__ == "__main__":
    main()
