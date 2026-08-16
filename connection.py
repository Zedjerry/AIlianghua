# -*- coding: utf-8 -*-
"""
connection.py — 连接重试/断线重连工具（阶段4）
=============================================
实盘交易最怕"连不上/中途断线"。本模块提供带指数退避的自动重试，
任何"连接类"操作（连券商、下行情、拉数据）都可以包一层，断线自动重连。

核心函数:
    with_retry(fn, retries=5, base_delay=2, backoff=2, on_retry=None)
        调用 fn()，失败按 2s→4s→8s... 退避重试，全部失败才抛异常；
        on_retry 可传入回调，在每次重试前执行（如发告警）。

用法:
    from connection import with_retry
    with_retry(lambda: broker.connect(), retries=3, base_delay=2,
               on_retry=lambda a, r, d, e: alert("WARN", f"连接失败，{d}秒后重试 {a}/{r}"))

独立演示（模拟一个"前3次必断"的假连接）:  python connection.py
"""

import time


def with_retry(fn, retries: int = 5, base_delay: float = 2.0,
               backoff: float = 2.0, on_retry=None):
    """
    带指数退避的重试包装器。

    参数:
        fn:        要执行的函数（无参，如 broker.connect）
        retries:   最多尝试次数（默认5次）
        base_delay:首次重试前的等待秒数
        backoff:   每次重试等待的倍率（2 → 2s, 4s, 8s...）
        on_retry:  可选回调 on_retry(attempt, retries, delay, exception)
    返回:
        fn() 的成功返回值
    抛出:
        最后一次尝试的异常
    """
    delay = base_delay
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt == retries:
                break
            if on_retry:
                on_retry(attempt, retries, delay, e)
            print(f"[重连] 第 {attempt} 次失败({type(e).__name__})，{delay:.0f} 秒后重试...", flush=True)
            time.sleep(delay)
            delay *= backoff
    raise last_err


# ---------- 独立演示/自测 ----------

class FlakyConnection:
    """模拟一个前 3 次连接必失败、之后成功的假连接"""

    def __init__(self):
        self.attempts = 0

    def connect(self):
        self.attempts += 1
        if self.attempts <= 3:
            raise ConnectionError(f"模拟断线 (第{self.attempts}次)")
        return f"连接成功 (第{self.attempts}次尝试)"


def _demo():
    print("===== 断线重连演示（前3次必断，应自动重连成功） =====\n")
    conn = FlakyConnection()
    t0 = time.time()

    def on_retry(attempt, retries, delay, err):
        print(f"   回调: 准备第 {attempt + 1}/{retries} 次重试, 等待 {delay:.0f}s")

    result = with_retry(conn.connect, retries=5, base_delay=0.2, backoff=1.5,
                        on_retry=on_retry)
    print(f"\n结果: {result}，总耗时 {time.time() - t0:.1f}s")
    assert result.startswith("连接成功")
    print("\n自测结果: [OK] 断线自动重连通过")

    print("\n===== 超过重试上限的演示（应抛异常） =====")
    conn2 = FlakyConnection()
    try:
        with_retry(conn2.connect, retries=2, base_delay=0.1)
        print("  异常未抛出（不对！）")
    except ConnectionError as e:
        print(f"  正确抛出异常: {e}")
    print("\n自测结果: [OK] 重试上限生效")


if __name__ == "__main__":
    _demo()
