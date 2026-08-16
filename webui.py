# -*- coding: utf-8 -*-
"""
webui.py — 量化系统可视化 UI（本地网页服务）
============================================
把整套系统搬进浏览器：实时看板 + 一键操作 + 自动刷新。

页面:
    概览   净值曲线 / 关键指标卡片
    信号   今日 Top20 清单
    模拟盘 持仓 / 现金 / 净值明细
    评估   信号质量评估 + 跨年稳健性
    告警   最新告警记录
操作(右上角):
    运行每日流程   = run_daily.py（信号→评估→模拟盘→看板）
    重置模拟盘     = 删除账户 → 重新跑模拟盘
    刷新图表       = 重新生成看板图片

启动:
    python webui.py                # 默认 http://127.0.0.1:8000
    python webui.py --port 9000    # 指定端口
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template_string, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

app = Flask(__name__)

# 后台任务状态（供前端轮询）
TASK = {"running": False, "name": "", "start": None, "finish": None,
        "exit": None, "log": "", "log_file": ""}


# ---------------- 后台任务 ----------------

def run_in_background(cmd: list, name: str):
    """在后台线程执行子命令，输出写入日志文件（避免管道，任何环境都稳定）"""
    def worker():
        TASK.update(running=True, name=name,
                    start=datetime.now().strftime("%H:%M:%S"),
                    finish=None, exit=None, log="", log_file="")
        log_dir = os.path.join(OUTPUT_DIR, "daily_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{name}.log")
        with open(log_path, "w", encoding="utf-8") as f:
            try:
                # 强制子进程 UTF-8 输出，避免中文乱码
                env = dict(os.environ, PYTHONIOENCODING="utf-8")
                r = subprocess.run([sys.executable, "-W", "ignore", "-u"] + cmd,
                                   cwd=BASE_DIR, stdout=f, stderr=subprocess.STDOUT,
                                   timeout=3600, env=env)
                TASK["exit"] = r.returncode
            except Exception as e:
                TASK["exit"] = -1
                with open(log_path, "a", encoding="utf-8") as f2:
                    f2.write(f"\n[异常] {e}\n")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                TASK["log"] = f.read()[-4000:]
        except Exception:
            pass
        TASK["log_file"] = log_path
        TASK["finish"] = datetime.now().strftime("%H:%M:%S")
        TASK["running"] = False
    threading.Thread(target=worker, daemon=True).start()


# ---------------- 数据读取（全部防御式） ----------------

def safe_read(path, **kw):
    try:
        return __import__("pandas").read_csv(path, **kw)
    except Exception:
        return None


def load_paper():
    try:
        with open(os.path.join(OUTPUT_DIR, "paper_account.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_alerts(n=10):
    try:
        with open(os.path.join(OUTPUT_DIR, "alerts.log"), "r", encoding="utf-8") as f:
            return f.readlines()[-n:][::-1]
    except Exception:
        return []


def load_names():
    df = safe_read(os.path.join(DATA_DIR, "stock_list.csv"), dtype={"code": str})
    return dict(zip(df["code"], df["name"])) if df is not None else {}


# ---------------- API ----------------

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/img/<path:name>")
def img(name):
    return send_from_directory(OUTPUT_DIR, name)


@app.route("/api/overview")
def api_overview():
    acc = load_paper()
    ov = {"equity": None, "cash": None, "positions": 0, "return": None,
          "signal_date": "-", "eval_forward": 0, "eval_total": 0,
          "win_rate": None, "alerts": load_alerts(5)}
    if acc:
        equity = float(acc.get("equity", 0))
        start = float(acc.get("start_capital", equity))
        ov["equity"] = round(equity)
        ov["cash"] = round(float(acc.get("cash", 0)))
        ov["positions"] = len(acc.get("positions", {}))
        ov["return"] = equity / start - 1 if start else None
    sig = safe_read(os.path.join(OUTPUT_DIR, "signals_today.csv"), dtype={"code": str})
    if sig is not None and not sig.empty:
        ov["signal_date"] = str(sig["date"].iloc[0])
    ev = safe_read(os.path.join(OUTPUT_DIR, "signal_evaluation.csv"))
    if ev is not None and not ev.empty:
        ov["eval_total"] = len(ev)
        if "来源" in ev.columns:
            fwd = ev[ev["来源"] == "forward"]
            ov["eval_forward"] = len(fwd)
            if len(fwd):
                ov["win_rate"] = (fwd["超额收益"] > 0).mean()
        else:
            ov["win_rate"] = (ev["超额收益"] > 0).mean()
    return jsonify(ov)


@app.route("/api/nav")
def api_nav():
    """模拟盘净值 vs 沪深300（JSON 数组）"""
    log = safe_read(os.path.join(OUTPUT_DIR, "paper_trade_log.csv"))
    nav, bench = [], []
    if log is not None:
        d = log[log["action"] == "净值"][["date", "equity"]]
        if not d.empty:
            base = float(d["equity"].iloc[0])
            nav = [{"date": r.date, "nav": float(r.equity) / base}
                   for r in d.itertuples()]
    idx = safe_read(os.path.join(DATA_DIR, "index_000300.csv"))
    if idx is not None and nav:
        import pandas as pd
        idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
        dates = {x["date"] for x in nav}
        b = idx[idx["date"].isin(dates)].reset_index(drop=True)
        if not b.empty:
            base = float(b["close"].iloc[0])
            bench = [{"date": r.date, "nav": float(r.close) / base}
                     for r in b.itertuples()]
    return jsonify({"nav": nav, "bench": bench})


@app.route("/api/signals")
def api_signals():
    sig = safe_read(os.path.join(OUTPUT_DIR, "signals_today.csv"), dtype={"code": str})
    if sig is None or sig.empty:
        return jsonify([])
    names = load_names()
    rows = []
    for _, r in sig.head(20).iterrows():
        rows.append({"code": r["code"], "name": r.get("name", names.get(r["code"], "")),
                     "close": round(float(r.get("close", 0)), 2),
                     "pred": round(float(r.get("pred_5d_return", 0)) * 100, 2)})
    return jsonify(rows)


@app.route("/api/account")
def api_account():
    acc = load_paper()
    if not acc:
        return jsonify({"cash": 0, "equity": 0, "holdings": []})
    names = load_names()
    pos = acc.get("positions", {})
    holdings = [{"code": c, "name": names.get(c, ""), "shares": int(s)}
                for c, s in pos.items()]
    return jsonify({"cash": round(float(acc.get("cash", 0))),
                    "equity": round(float(acc.get("equity", 0))),
                    "start": round(float(acc.get("start_capital", 0))),
                    "holdings": holdings})


@app.route("/api/evaluation")
def api_evaluation():
    ev = safe_read(os.path.join(OUTPUT_DIR, "signal_evaluation.csv"))
    rows = []
    if ev is not None and not ev.empty:
        for _, r in ev.iterrows():
            rows.append({"date": r["date"],
                         "signal": round(r["信号5日收益"] * 100, 2),
                         "bench": round(r["沪深300同期"] * 100, 2),
                         "excess": round(r["超额收益"] * 100, 2),
                         "source": r.get("来源", "?")})
    wf = safe_read(os.path.join(OUTPUT_DIR, "walkforward_report.csv"))
    wf_summary = None
    if wf is not None and not wf.empty:
        wf_summary = {"periods": len(wf),
                      "avg_ic": round(wf["IC"].mean(), 4),
                      "ic_pos_ratio": round((wf["IC"] > 0).mean(), 3),
                      "avg_excess": round(wf["平均超额(5日)"].mean() * 100, 2)}
    return jsonify({"rows": rows, "walkforward": wf_summary})


@app.route("/api/alerts")
def api_alerts():
    return jsonify([a.strip() for a in load_alerts(20)])


@app.route("/api/task")
def api_task():
    return jsonify(TASK)


@app.route("/api/run_daily", methods=["POST"])
def api_run_daily():
    if TASK["running"]:
        return jsonify({"ok": False, "msg": f"已有任务在运行: {TASK['name']}"})
    run_in_background(["run_daily.py"], "daily")
    return jsonify({"ok": True, "msg": "已启动每日流程（信号→评估→模拟盘→看板）"})


@app.route("/api/reset_account", methods=["POST"])
def api_reset_account():
    if TASK["running"]:
        return jsonify({"ok": False, "msg": f"已有任务在运行: {TASK['name']}"})
    try:
        os.remove(os.path.join(OUTPUT_DIR, "paper_account.json"))
    except FileNotFoundError:
        pass
    run_in_background(["step7_paper_trade.py"], "reset")
    return jsonify({"ok": True, "msg": "已重置模拟盘并重新运行"})


@app.route("/api/refresh_charts", methods=["POST"])
def api_refresh_charts():
    try:
        import dashboard
        dashboard.chart_nav()
        dashboard.chart_excess()
        dashboard.chart_holdings(load_names())
        return jsonify({"ok": True, "msg": "图表已刷新"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


# ---------------- 页面模板 ----------------

HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 量化系统 UI</title>
<style>
 body{font-family:'Microsoft YaHei',sans-serif;background:#0f1420;color:#e8eaf0;margin:0;padding:18px}
 h1{font-size:20px;margin:0;display:inline-block}
 .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px}
 .btn{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:13px}
 .btn:hover{background:#1d4ed8}.btn:disabled{background:#475569;cursor:not-allowed}
 .btn.orange{background:#d97706}.btn.orange:hover{background:#b45309}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
 .card{background:#1a2133;border-radius:10px;padding:14px 16px}
 .k{font-size:12px;color:#8b93a7}.v{font-size:22px;font-weight:bold;margin:4px 0}
 .s{font-size:12px;color:#34d399}
 .panel{background:#1a2133;border-radius:10px;padding:16px;margin-bottom:14px}
 .panel h2{font-size:15px;margin:0 0 12px;border-left:3px solid #2563eb;padding-left:8px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{padding:7px 10px;border-bottom:1px solid #232c42;text-align:left}
 th{color:#8b93a7;font-weight:normal}
 .pos{color:#34d399}.neg{color:#f87171}
 .tab{display:inline-block;padding:8px 16px;cursor:pointer;border-radius:8px 8px 0 0;background:#141a2b;margin-right:4px;font-size:13px}
 .tab.active{background:#1a2133;color:#60a5fa}
 .page{display:none}.page.active{display:block}
 .badge{font-size:12px;background:#1f2937;border-radius:6px;padding:2px 8px;margin-left:8px;color:#9ca3af}
 pre{font-size:12px;background:#0b0f1a;padding:10px;border-radius:8px;overflow:auto;max-height:300px;white-space:pre-wrap}
 img{max-width:100%;border-radius:8px}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
 @media(max-width:900px){.grid2{grid-template-columns:1fr}}
 .empty{color:#8b93a7;font-size:13px}
</style></head><body>
<div class="top">
 <h1>AI 量化系统 <span id="sigdate" class="badge"></span></h1>
 <div>
   <button class="btn" onclick="runAction('/api/run_daily')">运行每日流程</button>
   <button class="btn orange" onclick="runAction('/api/reset_account')">重置模拟盘</button>
   <button class="btn" onclick="runAction('/api/refresh_charts')">刷新图表</button>
 </div>
</div>
<div id="taskbar" style="margin-bottom:14px;font-size:13px;color:#8b93a7"></div>

<div id="tabs">
 <span class="tab active" data-p="overview" onclick="showPage(this)">概览</span>
 <span class="tab" data-p="signals" onclick="showPage(this)">信号</span>
 <span class="tab" data-p="account" onclick="showPage(this)">模拟盘</span>
 <span class="tab" data-p="eval" onclick="showPage(this)">评估</span>
 <span class="tab" data-p="alerts" onclick="showPage(this)">告警</span>
</div>

<div id="overview" class="page active">
 <div class="cards" id="cards"></div>
 <div class="grid2">
  <div class="panel"><h2>模拟盘净值 vs 沪深300</h2><img id="navimg" src="/img/dashboard_nav.png?t=0"></div>
  <div class="panel"><h2>信号超额收益</h2><img id="excessimg" src="/img/dashboard_excess.png?t=0"></div>
 </div>
</div>

<div id="signals" class="page">
 <div class="panel"><h2>今日信号 Top20（预测未来5日涨幅）</h2>
  <table><thead><tr><th>代码</th><th>名称</th><th>收盘价</th><th>预测涨幅%</th></tr></thead>
  <tbody id="sigbody"></tbody></table></div>
</div>

<div id="account" class="page">
 <div class="cards" id="acccards"></div>
 <div class="grid2">
  <div class="panel"><h2>当前持仓</h2>
   <table><thead><tr><th>代码</th><th>名称</th><th>股数</th></tr></thead>
   <tbody id="posbody"></tbody></table></div>
  <div class="panel"><h2>持仓分布</h2><img id="holdimg" src="/img/dashboard_holdings.png?t=0"></div>
 </div>
</div>

<div id="eval" class="page">
 <div class="cards" id="evalcards"></div>
 <div class="panel"><h2>信号质量评估明细</h2>
  <table><thead><tr><th>日期</th><th>信号5日收益%</th><th>沪深300同期%</th><th>超额%</th><th>来源</th></tr></thead>
  <tbody id="evalbody"></tbody></table></div>
</div>

<div id="alerts" class="page">
 <div class="panel"><h2>告警记录</h2><div id="alertbody" class="empty"></div></div>
</div>

<script>
function showPage(el){
 document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
 el.classList.add('active');
 document.getElementById(el.dataset.p).classList.add('active');
}
async function get(url){const r=await fetch(url);return r.json();}
async function runAction(url){
 const r=await fetch(url,{method:'POST'});const j=await r.json();
 alert(j.msg);refresh();
}
function fmtPct(x){return (x>=0?'+':'')+ (x*100).toFixed(2)+'%';}
async function refresh(){
 // 概览卡片
 const ov=await get('/api/overview');
 document.getElementById('sigdate').textContent='信号日 '+ov.signal_date;
 const cards=document.getElementById('cards'); cards.innerHTML='';
 const items=[
  ['模拟盘净值',ov.equity==null?'-':ov.equity.toLocaleString()+' 元',ov.return==null?'':fmtPct(ov.return)],
  ['当前持仓',ov.positions+' 只','现金 '+(ov.cash==null?'-':ov.cash.toLocaleString())],
  ['信号评估',ov.eval_total+' 期','向前验证 '+ov.eval_forward+' 期'],
  ['跑赢胜率',ov.win_rate==null?'-':(ov.win_rate*100).toFixed(0)+'%','>60% 才算达标'],
 ];
 items.forEach(([k,v,s])=>cards.insertAdjacentHTML('beforeend',
   `<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`));
 // 信号
 const sig=await get('/api/signals');
 document.getElementById('sigbody').innerHTML=sig.map(r=>
   `<tr><td>${r.code}</td><td>${r.name}</td><td>${r.close}</td><td class="pos">${r.pred}%</td></tr>`).join('');
 // 模拟盘
 const acc=await get('/api/account');
 document.getElementById('acccards').innerHTML=[
   ['账户净值',acc.equity.toLocaleString()+' 元','初始 '+acc.start.toLocaleString()],
   ['可用现金',acc.cash.toLocaleString()+' 元','持仓 '+acc.holdings.length+' 只'],
 ].map(([k,v,s])=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join('');
 document.getElementById('posbody').innerHTML=acc.holdings.map(h=>
   `<tr><td>${h.code}</td><td>${h.name}</td><td>${h.shares}</td></tr>`).join('')
   || '<tr><td colspan="3" class="empty">空仓</td></tr>';
 // 评估
 const ev=await get('/api/evaluation');
 const ec=document.getElementById('evalcards'); ec.innerHTML='';
 if(ev.walkforward) ec.insertAdjacentHTML('beforeend',
   `<div class="card"><div class="k">跨年稳健性(滚动样本外)</div><div class="v">${ev.walkforward.periods}期</div>`+
   `<div class="s">平均IC ${ev.walkforward.avg_ic} · IC为正 ${(ev.walkforward.ic_pos_ratio*100).toFixed(0)}% · 平均超额 ${ev.walkforward.avg_excess}%</div></div>`);
 document.getElementById('evalbody').innerHTML=ev.rows.map(r=>
   `<tr><td>${r.date}</td><td class="${r.signal>=0?'pos':'neg'}">${r.signal}</td>`+
   `<td class="${r.bench>=0?'pos':'neg'}">${r.bench}</td>`+
   `<td class="${r.excess>=0?'pos':'neg'}">${r.excess}</td><td>${r.source}</td></tr>`).join('')
   || '<tr><td colspan="5" class="empty">暂无评估数据</td></tr>';
 // 告警
 const al=await get('/api/alerts');
 document.getElementById('alertbody').innerHTML=al.join('<br>')||'暂无告警';
 // 任务状态
 const tk=await get('/api/task');
 const tb=document.getElementById('taskbar');
 if(tk.running){tb.textContent='⏳ 正在运行: '+tk.name+'（'+tk.start+' 开始）…';}
 else if(tk.finish){tb.textContent='任务 '+tk.name+' 已于 '+tk.finish+' 结束'+(tk.exit===0?' [成功]':' [失败,退出码 '+tk.exit+']')+' · 日志: '+tk.log_file;}
 else{tb.textContent='系统就绪';}
 // 图表加时间戳刷新
 const t=Date.now();
 document.getElementById('navimg').src='/img/dashboard_nav.png?t='+t;
 document.getElementById('excessimg').src='/img/dashboard_excess.png?t='+t;
 document.getElementById('holdimg').src='/img/dashboard_holdings.png?t='+t;
}
refresh();
setInterval(refresh, 20000);  // 每20秒自动刷新
</script>
</body></html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"AI 量化 UI 已启动: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
