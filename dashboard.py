# -*- coding: utf-8 -*-
"""
dashboard.py — 量化看板（可视化面板）
=====================================
把模拟盘、今日信号、信号评估、告警记录等所有输出汇总成一个网页，
打开浏览器就能直观看到系统状态，不用逐个翻 CSV。

用法:
    python dashboard.py             # 生成 output/dashboard.html 并自动打开浏览器
    python dashboard.py --no-open   # 只生成不打开（适合脚本/服务器环境）

输出:
    output/dashboard.html           自包含网页（无外部依赖，离线可看）
    output/dashboard_nav.png        模拟盘净值 vs 沪深300
    output/dashboard_excess.png     信号超额收益柱状图
    output/dashboard_holdings.png   当前持仓分布
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# 暗色专业主题（与 UI 一致）: 深色底 + 亮色文字 + A股红涨绿跌
plt.rcParams.update({
    "figure.facecolor": "#0b101d",
    "axes.facecolor": "#111827",
    "axes.edgecolor": "#27304a",
    "axes.labelcolor": "#cbd5e1",
    "text.color": "#e2e8f0",
    "xtick.color": "#7d8aa3",
    "ytick.color": "#7d8aa3",
    "grid.color": "#1f2a44",
    "legend.facecolor": "#111827",
    "legend.edgecolor": "#27304a",
    "savefig.facecolor": "#0b101d",
})

UP = "#ef4444"    # A股: 涨=红
DOWN = "#10b981"  # A股: 跌=绿


# ---------- 坐标轴工具 ----------

def _idx_date_axis(ax, dates, n_ticks=6):
    """位置型X轴: 稀疏刻度 + 中文年月(如 2026年6月) + 水平排列"""
    n = len(dates)
    if n <= 1:
        return
    step = max(1, (n - 1) // (n_ticks - 1))
    pos = list(range(0, n, step))
    labels = [f"{str(dates[i])[:4]}年{int(str(dates[i])[5:7])}月" for i in pos]
    ax.set_xticks(pos)
    ax.set_xticklabels(labels, rotation=0, ha="center")


def _dt_date_axis(ax, n_ticks=6):
    """时间型X轴: 中文年月 + 水平排列（用于折线图）"""
    import matplotlib.dates as mdates
    xmin, xmax = ax.get_xlim()
    months = max(1, int((xmax - xmin) / 30.44 / max(1, (n_ticks - 1))))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=months))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y年%m月"))
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center")

DATA_DIR = "data"
OUTPUT_DIR = "output"
HTML_FILE = os.path.join(OUTPUT_DIR, "dashboard.html")


# ---------- 数据读取（全部防御式，缺文件不报错） ----------

def safe_read(path, **kwargs):
    try:
        return pd.read_csv(path, **kwargs)
    except Exception:
        return None


def load_paper():
    """模拟盘账户状态"""
    path = os.path.join(OUTPUT_DIR, "paper_account.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    except Exception:
        return None


def load_names():
    df = safe_read(os.path.join(DATA_DIR, "stock_list.csv"), dtype={"code": str})
    return dict(zip(df["code"], df["name"])) if df is not None else {}


# ---------- 图表 ----------

def chart_nav():
    """模拟盘净值 vs 沪深300"""
    log = safe_read(os.path.join(OUTPUT_DIR, "paper_trade_log.csv"))
    if log is None:
        return None
    nav = log[log["action"] == "净值"][["date", "equity"]].copy()
    if nav.empty:
        return None
    nav["nav"] = nav["equity"].astype(float) / nav["equity"].astype(float).iloc[0]
    idx = safe_read(os.path.join(DATA_DIR, "index_000300.csv"))
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(pd.to_datetime(nav["date"]), nav["nav"], label="模拟盘", linewidth=1.8, color="#3b82f6")
    if idx is not None:
        idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
        bench = idx[idx["date"].isin(nav["date"])].reset_index(drop=True)
        if not bench.empty:
            bench["bnav"] = bench["close"] / bench["close"].iloc[0]
            ax.plot(pd.to_datetime(bench["date"]), bench["bnav"], label="沪深300", linewidth=1.4, alpha=0.75, color="#8b5cf6")
    ax.set_title("模拟盘净值 vs 沪深300", color="#e2e8f0")
    ax.set_ylabel("净值（起点=1，1.0=初始资金）", fontsize=11)
    ax.legend(); ax.grid(alpha=0.3)
    _dt_date_axis(ax)
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "dashboard_nav.png")
    fig.savefig(path, dpi=120); plt.close(fig)
    return path


def chart_excess():
    """信号超额收益柱状图（百分比）"""
    ev = safe_read(os.path.join(OUTPUT_DIR, "signal_evaluation.csv"))
    if ev is None or ev.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 3.6))
    colors = [DOWN if x < 0 else UP for x in ev["超额收益"]]  # A股: 红涨绿跌
    ax.bar(range(len(ev)), ev["超额收益"] * 100, color=colors)  # 转为百分数显示
    ax.axhline(0, color="#7d8aa3", linewidth=0.8)
    ax.set_title("信号超额收益（每期 5 日，相对沪深300）", color="#e2e8f0")
    ax.set_ylabel("超额收益（%）", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    _idx_date_axis(ax, ev["date"])
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "dashboard_excess.png")
    fig.savefig(path, dpi=120); plt.close(fig)
    return path


def chart_holdings(names: dict):
    """当前持仓分布饼图"""
    acc = load_paper()
    if not acc or not acc.get("positions"):
        return None
    pos = acc["positions"]
    # 用最近收盘价估算市值（简化：直接用账户文件没有市值，这里只画数量分布）
    fig, ax = plt.subplots(figsize=(7, 4.5))
    codes = list(pos.keys())
    labels = [f"{c} {names.get(c, '')}" for c in codes]
    ax.pie(list(pos.values()), labels=labels, autopct="%1.0f%%", startangle=90,
           textprops={"fontsize": 8})
    ax.set_title(f"当前持仓 {len(pos)} 只（按股数占比）")
    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "dashboard_holdings.png")
    fig.savefig(path, dpi=120); plt.close(fig)
    return path


# ---------- HTML ----------

def build_html(nav_img, excess_img, holdings_img):
    names = load_names()
    acc = load_paper()

    # 概览卡片
    cards = []
    if acc:
        equity = float(acc.get("equity", 0))
        start = float(acc.get("start_capital", equity))
        ret = equity / start - 1 if start else 0
        cards.append(("模拟盘净值", f"{equity:,.0f} 元", f"累计 {ret:+.2%}"))
        cards.append(("当前持仓", f"{len(acc.get('positions', {}))} 只", f"现金 {float(acc.get('cash', 0)):,.0f}"))
    else:
        cards.append(("模拟盘", "未启动", "先运行 step7"))

    # 今日信号
    sig = safe_read(os.path.join(OUTPUT_DIR, "signals_today.csv"), dtype={"code": str})
    sig_rows = ""
    if sig is not None and not sig.empty:
        sig_date = str(sig["date"].iloc[0])
        cards.insert(0, ("最新信号日", sig_date, f"Top {len(sig)}"))
        top = sig.head(10)
        for _, r in top.iterrows():
            name = r.get("name", names.get(r["code"], ""))
            sig_rows += (f"<tr><td>{r['code']}</td><td>{name}</td>"
                         f"<td>{r.get('close', 0):.2f}</td>"
                         f"<td>{float(r.get('pred_5d_return', 0)):.2%}</td></tr>")
    else:
        sig_rows = "<tr><td colspan='4'>暂无信号（先运行 step5）</td></tr>"

    # 持仓表
    pos_rows = ""
    if acc and acc.get("positions"):
        for code, shares in acc["positions"].items():
            pos_rows += f"<tr><td>{code}</td><td>{names.get(code, '')}</td><td>{shares}</td></tr>"
    else:
        pos_rows = "<tr><td colspan='3'>空仓</td></tr>"

    # 信号评估表
    ev = safe_read(os.path.join(OUTPUT_DIR, "signal_evaluation.csv"))
    ev_rows = ""
    if ev is not None and not ev.empty:
        for _, r in ev.iterrows():
            cls = "pos" if r["超额收益"] > 0 else "neg"
            ev_rows += (f"<tr><td>{r['date']}</td><td>{r['信号5日收益']:.2%}</td>"
                        f"<td>{r['沪深300同期']:.2%}</td>"
                        f"<td class='{cls}'>{r['超额收益']:+.2%}</td></tr>")
        wins = (ev["超额收益"] > 0).mean()
        cards.append(("信号胜率", f"{wins:.0%}", f"{len(ev)} 期"))
    else:
        ev_rows = "<tr><td colspan='4'>暂无评估数据（信号生成5日后自动核算）</td></tr>"

    # 告警
    alerts = []
    try:
        with open(os.path.join(OUTPUT_DIR, "alerts.log"), "r", encoding="utf-8") as f:
            alerts = f.readlines()[-8:]
    except Exception:
        pass
    alert_rows = "".join(f"<tr><td>{a.strip()}</td></tr>" for a in reversed(alerts)) or \
        "<tr><td>暂无告警记录</td></tr>"

    cards_html = "".join(
        f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div>"
        f"<div class='s'>{s}</div></div>"
        for k, v, s in cards)

    img = lambda p: (f"<img src='{os.path.basename(p)}' style='width:100%'/>"
                     if p else "<p class='empty'>暂无数据</p>")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>AI 量化看板</title>
<style>
 body{{font-family:'Microsoft YaHei',sans-serif;background:#f5f6fa;margin:0;padding:20px;color:#333}}
 h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px;border-left:4px solid #3498db;padding-left:8px}}
 .cards{{display:flex;flex-wrap:wrap;gap:12px}}
 .card{{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 4px rgba(0,0,0,.08);min-width:150px}}
 .k{{font-size:12px;color:#888}} .v{{font-size:22px;font-weight:bold;margin:4px 0}}
 .s{{font-size:12px;color:#27ae60}}
 .panel{{background:#fff;border-radius:10px;padding:16px;margin-top:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{padding:6px 10px;border-bottom:1px solid #eee;text-align:left}}
 th{{background:#f8f9fb}} .pos{{color:#27ae60;font-weight:bold}} .neg{{color:#c0392b;font-weight:bold}}
 .empty{{color:#999}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
 @media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>📊 AI 量化看板</h1>
<div class='cards'>{cards_html}</div>
<div class='grid'>
 <div class='panel'><h2>模拟盘净值</h2>{img(nav_img)}</div>
 <div class='panel'><h2>信号超额收益</h2>{img(excess_img)}</div>
</div>
<div class='grid'>
 <div class='panel'><h2>今日信号 Top10</h2><table><tr><th>代码</th><th>名称</th><th>收盘价</th><th>预测5日涨幅</th></tr>{sig_rows}</table></div>
 <div class='panel'><h2>当前持仓</h2><table><tr><th>代码</th><th>名称</th><th>股数</th></tr>{pos_rows}</table></div>
</div>
<div class='grid'>
 <div class='panel'><h2>信号质量评估</h2><table><tr><th>日期</th><th>信号5日收益</th><th>沪深300同期</th><th>超额</th></tr>{ev_rows}</table></div>
 <div class='panel'><h2>持仓分布</h2>{img(holdings_img)}</div>
</div>
<div class='panel'><h2>最近告警</h2><table>{alert_rows}</table></div>
<p style='color:#999;font-size:12px;margin-top:20px'>由 dashboard.py 自动生成 · 运行 <code>python dashboard.py</code> 刷新</p>
</body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-open", action="store_true", help="只生成不打开浏览器")
    args = parser.parse_args()

    print("生成看板图表...", flush=True)
    nav_img = chart_nav()
    excess_img = chart_excess()
    holdings_img = chart_holdings(load_names())

    html = build_html(nav_img, excess_img, holdings_img)
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 看板已生成: {HTML_FILE}", flush=True)

    if not args.no_open:
        import webbrowser
        webbrowser.open("file:///" + os.path.abspath(HTML_FILE).replace("\\", "/"))
        print("[OK] 已在浏览器打开（若未弹出请手动打开上面的路径）", flush=True)


if __name__ == "__main__":
    main()
