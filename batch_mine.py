# -*- coding: utf-8 -*-
"""
batch_mine.py — 批量挖矿（挂机攒公式池）
========================================
遍历一批股票的日线旧数据，逐只运行 AlphaMaster RL 挖矿，自动入库 formulas/。

用法:
    python batch_mine.py --stocks 000858 601318 600000     # 指定股票
    python batch_mine.py --limit 10                        # 自动挑前10只（按代码排序）
    python batch_mine.py --steps 600                       # 每只训练步数（默认600）
    python batch_mine.py --all --steps 300                 # 全部股票（17091只，慎用！）

说明:
    - 已挖过的股票自动跳过（加 --force 重挖）
    - 逐只顺序挖矿，单只失败不影响后续
    - 进度写入 output/batch_mine.log
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = r"D:\量化\数据\A股数据 (1)\parquet\stocks"
FORMULA_DIR = os.path.join(BASE_DIR, "formulas")
LOG_FILE = os.path.join(BASE_DIR, "output", "batch_mine.log")
os.makedirs(FORMULA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# 默认推荐批次：沪深300 里流动性好、有代表性的股票
DEFAULT_STOCKS = ["000858", "601318", "600000", "000333", "600887",
                  "601398", "600030", "601166", "600900", "000651",
                  "601888", "600276", "600028", "601012", "600309"]


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def find_daily_files() -> dict:
    """扫描旧数据目录，返回 {code: parquet路径}（仅日线）"""
    found = {}
    if not os.path.isdir(DATA_DIR):
        return found
    for f in os.listdir(DATA_DIR):
        if f.endswith("_daily.parquet"):
            code = f.rsplit("_", 1)[0]
            if code.isdigit():
                found[code] = os.path.join(DATA_DIR, f)
    return found


def mine_one(code: str, path: str, steps: int, force: bool) -> str:
    """挖一只，返回 'ok' / 'skip' / 'fail'"""
    out = os.path.join(FORMULA_DIR, f"{code}_formula.json")
    if os.path.exists(out) and not force:
        return "skip"
    log(f"  [挖矿] {code} ({path}) 步数={steps} ...")
    r = subprocess.run(
        [sys.executable, "-W", "ignore", "-u",
         os.path.join(BASE_DIR, "mine_factor.py"),
         "--file", path, "--steps", str(steps)],
        cwd=BASE_DIR, timeout=7200,
    )
    if r.returncode == 0 and os.path.exists(out):
        log(f"  [完成] {code} 公式已入库")
        return "ok"
    log(f"  [失败] {code} 退出码 {r.returncode}")
    return "fail"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", nargs="*", default=None, help="指定股票代码列表")
    parser.add_argument("--limit", type=int, default=None, help="自动挑前N只（按代码排序）")
    parser.add_argument("--all", action="store_true", help="全部日线文件（慎用）")
    parser.add_argument("--steps", type=int, default=600, help="每只训练步数")
    parser.add_argument("--force", action="store_true", help="已挖过的也重挖")
    args = parser.parse_args()

    files = find_daily_files()
    if not files:
        raise SystemExit(f"旧数据目录不存在或无日线文件: {DATA_DIR}")

    if args.stocks:
        codes = [c for c in args.stocks if c in files]
        missing = [c for c in args.stocks if c not in files]
        if missing:
            log(f"[警告] 以下股票没有日线文件: {missing}")
    elif args.all:
        codes = sorted(files.keys())
    else:
        codes = sorted(DEFAULT_STOCKS, key=lambda c: (c not in files, c))
        if args.limit:
            codes = sorted(files.keys())[:args.limit]

    log(f"===== 批量挖矿开始: {len(codes)} 只 × {args.steps} 步 =====")
    ok = skip = fail = 0
    for code in codes:
        try:
            result = mine_one(code, files[code], args.steps, args.force)
        except Exception as e:
            result = "fail"
            log(f"  [异常] {code}: {e}")
        ok += result == "ok"
        skip += result == "skip"
        fail += result == "fail"

    log(f"===== 批量挖矿结束: 新挖 {ok} 只 | 跳过 {skip} 只 | 失败 {fail} 只 =====")
    log(f"公式池现有: {sorted(f.split('_')[0] for f in os.listdir(FORMULA_DIR) if f.endswith('.json'))}")


if __name__ == "__main__":
    main()
