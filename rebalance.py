# -*- coding: utf-8 -*-
"""
rebalance.py — 调仓决策纯函数（模拟盘与实盘共用）
==================================================
把「根据目标名单算出买卖订单」的逻辑抽成纯函数:
    - 不依赖任何交易接口、不读写文件、不碰时间；
    - 输入: 当前持仓 / 目标名单 / 现金 / 当日价格 / 参数
    - 输出: 订单列表 + 调整后的持仓 + 调整后的现金

这样模拟盘(step7)和实盘(trade_qmt)共用同一套调仓逻辑，
将来接 QMT 时只需要把订单「执行」换成真实下单，决策不会走样。

独立演示:  python rebalance.py
"""

from dataclasses import dataclass, field


@dataclass
class Order:
    """一条买卖指令"""
    action: str        # "买" / "卖"
    code: str
    shares: int
    price: float
    note: str = ""


@dataclass
class RebalanceResult:
    orders: list = field(default_factory=list)
    positions: dict = field(default_factory=dict)  # {code: shares}
    cash: float = 0.0


def compute_orders(holdings: dict, target_codes: list, cash: float,
                   prices: dict, top_k: int = 20, cost: float = 0.002,
                   max_position_pct: float = 0.10,
                   allow_buy: bool = True,
                   block_buy: set = None, block_sell: set = None) -> RebalanceResult:
    """
    纯函数：给定当前状态，算出本次调仓的所有订单。

    参数:
        holdings:      当前持仓 {code: 股数}
        target_codes:  目标名单（如今日信号 Top20 的代码列表）
        cash:          可用现金
        prices:        当日价格 {code: 收盘价}
        top_k:         目标持仓数量
        cost:          单边交易成本比例
        max_position_pct: 单票市值上限占总资产比例
        allow_buy:     False 时只卖不买（风控熔断模式）
        block_buy:     涨停/停牌无法买入的代码集合（默认空）
        block_sell:    跌停/停牌无法卖出的代码集合（默认空）
    返回:
        RebalanceResult(orders, positions, cash)
    """
    block_buy = block_buy or set()
    block_sell = block_sell or set()
    result = RebalanceResult(positions=dict(holdings), cash=cash)

    # ---------- 1) 卖出: 已持有但不在目标名单 ----------
    for code in list(result.positions.keys()):
        if code not in target_codes:
            price = prices.get(code)
            shares = result.positions.pop(code)
            if price is None:
                result.orders.append(Order("卖", code, shares, 0.0, "无价格，按0回收"))
                continue
            if code in block_sell:
                result.positions[code] = shares          # 卖不掉，先留着
                result.orders.append(Order("卖", code, 0, price, "跌停无法卖出，下期再试"))
                continue
            result.cash += shares * price * (1 - cost)
            result.orders.append(Order("卖", code, shares, price, "退出名单"))

    # ---------- 2) 买入: 目标名单内且未持有（等权配置） ----------
    if not allow_buy:
        return result  # 风控熔断: 只卖不买

    equity = result.cash + sum(
        s * prices.get(c, 0.0) for c, s in result.positions.items())
    target_value = equity / top_k

    for code in target_codes:
        if code in result.positions:
            continue
        if len(result.positions) >= top_k:
            break  # 持仓数已达上限，停止买入（资金小时会在名单里顺延找买得起的）
        price = prices.get(code)
        if price is None:
            result.orders.append(Order("买", code, 0, 0.0, "当日无价格(停牌/未上市)，跳过"))
            continue
        if code in block_buy:
            result.orders.append(Order("买", code, 0, price, "涨停无法买入，下期再试"))
            continue

        # 风控: 单票市值上限（目标等权金额与上限取小者）
        budget = min(target_value, equity * max_position_pct)
        shares = int(budget / price / 100) * 100      # A股按手(100股)交易
        if shares <= 0:
            result.orders.append(Order("买", code, 0, price, "资金不足一手，跳过"))
            continue

        cost_money = shares * price * (1 + cost)
        if cost_money > result.cash:                  # 现金不够则降量
            shares = int(result.cash / (price * (1 + cost)) / 100) * 100
            if shares <= 0:
                result.orders.append(Order("买", code, 0, price, "现金不足一手，跳过"))
                continue
            cost_money = shares * price * (1 + cost)

        result.cash -= cost_money
        result.positions[code] = result.positions.get(code, 0) + shares
        result.orders.append(Order("买", code, shares, price, "进入名单"))

    return result


# ---------- 独立演示/自测 ----------

def _demo():
    print("===== 调仓决策自测 =====\n")
    holdings = {"000001": 1000}                  # 当前持有 000001
    target = ["000001", "300750", "600519"]      # 新名单: 保留000001, 尝试买入两只
    prices = {"000001": 11.0, "300750": 180.0, "600519": 1500.0}
    cash = 100000.0

    res = compute_orders(holdings, target, cash, prices, top_k=3, max_position_pct=0.5)
    print(f"持仓: {holdings}  现金: {cash:.0f}  目标: {target}")
    print(f"\n订单({len(res.orders)} 条):")
    for o in res.orders:
        print(f"  {o.action} {o.code} {o.shares}股 @ {o.price:.2f}  备注: {o.note}")
    print(f"\n调仓后持仓: {res.positions}")
    print(f"调仓后现金: {res.cash:.2f}")

    # 校验: 名单内继续持有; 300750 应买入 200 股; 600519 一手太贵应跳过
    assert res.positions.get("000001") == 1000
    assert res.positions.get("300750") == 200
    assert "600519" not in res.positions

    # 涨跌停限制自测: 涨停的买不进、跌停的卖不出
    res2 = compute_orders({"000001": 1000}, ["000001", "300750"], 100000.0,
                          {"000001": 11.0, "300750": 180.0},
                          top_k=3, max_position_pct=0.5, block_buy={"300750"})
    assert "300750" not in res2.positions, "涨停的股票不应买入"
    res3 = compute_orders({"000001": 1000}, ["000002"], 100000.0,
                          {"000001": 11.0, "000002": 5.0},
                          top_k=3, max_position_pct=0.5, block_sell={"000001"})
    assert res3.positions.get("000001") == 1000, "跌停的股票不应卖出"

    print("\n自测结果: [OK] 通过（名单内的保留、便宜的买入、一手买不起的跳过、涨跌停受限）")


if __name__ == "__main__":
    _demo()
