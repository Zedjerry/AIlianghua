# 阶段3 指南：对接 QMT 实现自动下单

> 前提：你的信号已通过模拟盘验证（胜率>60%、平均超额>0），现在要把「信号」变成「自动买卖」。
> 本指南基于公开资料整理（东莞证券已确认支持 QMT 量化交易），具体以你的客户经理答复为准。

---

## 1. QMT 是什么

**QMT（迅投 Quant Multi-Trade）** 是国内券商提供给散户/机构的官方量化交易客户端，配套 **miniQMT** 模式允许用 **Python 直接调用 API** 实现自动下单。

- 行情：`xtquant.xtdata`（实时/历史行情）
- 交易：`xtquant.xttrader`（下单、撤单、持仓查询）
- 官方文档：迅投 xtquant 文档（搜索 "xtquant python"）

---

## 2. 开通步骤（东莞证券）

1. **联系你的客户经理**（或营业部），说："我要开通 QMT/miniQMT 量化交易权限"；
   - 询问：是否有资产门槛（常见 2万~50万不等，以券商当期政策为准）、佣金费率；
   - 若客户经理不熟悉，可要求在「网上营业厅/手机APP」找量化交易入口，或申请开通。
2. **下载客户端**：东莞证券官网或客户经理提供 QMT 客户端安装包（含 miniQMT 模式）。
3. **登录并验证**：用资金账号登录，确认 miniQMT 模式可用、能连上行情与交易服务器。
4. **先做模拟/小额测试**：用 1 手或最小单位手工验证下单通道通畅。

> 如果 QMT 开通受阻，备选路线：**vnpy**（开源，支持多家券商柜台接口）、或换一家 QMT 门槛低的券商（如国金证券）。

---

## 3. miniQMT Python API 预览

```python
# 安装: pip install xtquant   （通常随客户端附带，或从官方获取）

from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

# 1. 连接客户端（需要先登录 QMT 客户端并开启 miniQMT）
path = r"D:\QMT\userdata_mini"          # 你本机的 miniQMT 数据目录
session_id = 123456
trader = XtQuantTrader(path, session_id)
trader.start()
account = StockAccount("你的资金账号")
trader.connect()

# 2. 下单（示例：买入 600519 茅台 100 股，限价 1700）
from xtquant.xtconstant import STOCK_BUY, FIX_PRICE
order_id = trader.order_stock(
    account, "600519.SH", STOCK_BUY, 100,
    FIX_PRICE, 1700.0, "quant_strategy_v1"
)
print("订单号:", order_id)

# 3. 查询持仓/资金
positions = trader.query_stock_positions(account)
assets = trader.query_stock_asset(account)
```

> ⚠️ 上面的代码是【预览】，实际使用时字段/接口以你拿到的最新 xtquant 版本为准。
> 自动下单前必须：模拟盘跑通 → 小额试单 → 加风控（见阶段4）。

---

## 4. 我们的信号系统如何对接（架构预览）

```
每天 16:00 定时任务
  ├─ step5_generate_signals.py  生成今日信号 (signals_today.csv)
  └─ step6_track_signals.py     存档 + 评估
                  │
阶段3 新增: trade_qmt.py（对接 QMT 自动下单）
  ├─ 读 signals_today.csv
  ├─ 对照当前持仓:
  │     · 在信号Top20中但没持有  → 买入（等权分配资金）
  │     · 已持有但不在Top20中    → 卖出
  │     · 已在Top20中           → 继续持有
  ├─ 下单前检查: 可用资金、涨跌停、停牌、最小交易单位(100股整数倍)
  ├─ 下单: 分批/限价, 记录成交回报
  └─ 异常处理: 下单失败重试、断线重连、发送告警
```

**这份 trade_qmt.py 等你的 QMT 权限开通后，由我帮你写并实测**——现在先不需要（也没有真实环境可测）。

---

## 5. 合规与风险提醒

- 只使用券商官方提供的 QMT/PTrade 通道，**不要**用非官方外挂/模拟按键方式下单；
- 自动交易必须设**当日最大亏损上限**、单票仓位上限、暂停开关；
- 策略参数、模型、代码都要**留档可回溯**；
- 实盘永远从最小资金开始，逐步验证、逐步放大。
