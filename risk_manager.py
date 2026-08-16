# -*- coding: utf-8 -*-
"""
risk_manager.py — 风控模块（阶段4 核心）
========================================
集中管理交易风控规则，供 step7 模拟盘和将来的 trade_qmt 实盘共用。

规则:
    1. 单日亏损熔断: 当日净值跌幅超过 max_daily_loss  → 暂停买入(只卖不买)
    2. 最大回撤熔断: 账户净值较历史高点回撤超过 max_drawdown → 清仓避险
    3. 单票仓位上限: max_position_pct（在 rebalance.py 下单时执行）

用法:
    from risk_manager import RiskManager
    rm = RiskManager(max_daily_loss=0.03, max_drawdown=0.15)
    decisions = rm.check(equity=..., prev_equity=..., peak_equity=..., cash=...)
    # decisions 是字符串列表, 如 ["halt_buy"] / ["halt_buy", "liquidate"]

check() 是纯函数（不读写外部状态），方便测试、也方便接入任何交易引擎。

独立演示:  python risk_manager.py
"""

from dataclasses import dataclass


@dataclass
class RiskManager:
    """风控规则配置与判定（纯逻辑，无副作用）"""
    max_daily_loss: float = 0.03     # 单日净值跌幅超过 3% → 熔断买入
    max_drawdown: float = 0.15       # 从历史高点回撤超过 15% → 清仓
    max_position_pct: float = 0.10   # 单票市值占比上限（配合 rebalance 使用）

    def check(self, equity: float, prev_equity: float,
              peak_equity: float, cash: float) -> list:
        """
        输入账户状态，返回需要触发的风控动作列表。
        返回的可能值:
            "halt_buy"   暂停买入（只卖不买）
            "liquidate"  清仓避险
        """
        actions = []

        # 规则1: 单日亏损熔断
        if prev_equity and equity < prev_equity * (1 - self.max_daily_loss):
            actions.append("halt_buy")

        # 规则2: 最大回撤熔断（回撤期间持续有效）
        if peak_equity and equity < peak_equity * (1 - self.max_drawdown):
            actions.append("liquidate")
            actions.append("halt_buy")

        return actions

    def summary(self, equity: float, prev_equity: float,
                peak_equity: float, cash: float) -> str:
        """人类可读的风控状态摘要"""
        daily_ret = equity / prev_equity - 1 if prev_equity else 0.0
        drawdown = equity / peak_equity - 1 if peak_equity else 0.0
        lines = [
            f"  当前净值: {equity:,.0f}",
            f"  今日涨跌: {daily_ret:+.2%}（熔断线 {-self.max_daily_loss:.0%}）",
            f"  距高点回撤: {drawdown:+.2%}（清仓线 {-self.max_drawdown:.0%}）",
            f"  可用现金: {cash:,.0f}",
        ]
        actions = self.check(equity, prev_equity, peak_equity, cash)
        lines.append(f"  触发动作: {actions if actions else '无'}")
        return "\n".join(lines)


# ---------- 独立演示/自测 ----------

def _demo():
    print("===== 风控模块自测（演示三种场景） =====\n")
    rm = RiskManager()

    print("[场景1] 正常状态: 净值 110000, 昨日 108000, 高点 112000, 现金 30000")
    print(rm.summary(110000, 108000, 112000, 30000))

    print("\n[场景2] 单日大跌 5%: 净值 104000, 昨日 110000, 高点 112000, 现金 30000")
    print(rm.summary(104000, 110000, 112000, 30000))

    print("\n[场景3] 高点回撤 20%: 净值 88000, 昨日 90000, 高点 112000, 现金 30000")
    print(rm.summary(88000, 90000, 112000, 30000))

    print("\n判定: 场景1应无动作; 场景2应['halt_buy']; 场景3应['halt_buy','liquidate']")
    ok = (rm.check(110000, 108000, 112000, 30000) == []
          and rm.check(104000, 110000, 112000, 30000) == ["halt_buy"]
          and sorted(rm.check(88000, 90000, 112000, 30000)) == ["halt_buy", "liquidate"])
    print(f"\n自测结果: {'[OK] 全部通过' if ok else '[失败] 有误'}")


if __name__ == "__main__":
    _demo()
