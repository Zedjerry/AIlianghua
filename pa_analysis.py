# -*- coding: utf-8 -*-
"""
pa_analysis.py — PA Agent 网页版（按 PA_Agent 框架重制）
========================================================
把 PA_Agent 的核心框架搬进我们的系统:
    ① 两阶段 LLM 分析: 市场诊断 → 交易决策
    ② 决策树闸门: 规则化路由（趋势/动量/量能/风险 四道闸门 → 策略路径）
    ③ 经验库: 每次分析落盘，后续分析可引用历史案例

数据全部来自我们已有的行情，不依赖 MT5/PyQt6，网页即开即用。

用法:
    python pa_analysis.py --code 600519          # 分析茅台（默认近120日）
    python pa_analysis.py --code 000001 --days 60

输出:
    output/pa_analysis.json      本次分析结果（webui 展示用）
    output/pa_experience.json    经验库（每次分析自动追加）
"""

import argparse
import json
import os

import pandas as pd

DATA_DIR = "data"
OUTPUT_DIR = "output"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_llm.json")
EXPERIENCE_FILE = os.path.join(OUTPUT_DIR, "pa_experience.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------- LLM 配置（与 market_diagnosis 共用） ----------------

def load_llm_config() -> dict:
    cfg = {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash",
           "api_key": os.environ.get("QUANT_LLM_API_KEY", ""), "timeout": 60}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if v})
    return cfg


def call_llm(cfg: dict, system: str, user: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg["timeout"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.2,
    )
    return resp.choices[0].message.content


# ---------------- ① 数据快照 ----------------

def build_snapshot(code: str, days: int = 120) -> dict:
    """从我们的行情数据提取单只股票最近 N 日的结构化快照"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    d = daily[daily["code"] == code].sort_values("date").tail(days).copy()
    if d.empty:
        raise SystemExit(f"没有 {code} 的行情数据")
    d["ret"] = d["close"].pct_change()
    c = d["close"]
    snap = {
        "code": code,
        "date": d["date"].iloc[-1],
        "close": round(float(c.iloc[-1]), 2),
        "ret_1d": round(float(d["ret"].iloc[-1] * 100), 2),
        "ret_5d": round(float((c.iloc[-1] / c.iloc[-6] - 1) * 100), 2) if len(d) > 6 else None,
        "ma5": round(float(c.rolling(5).mean().iloc[-1]), 2),
        "ma20": round(float(c.rolling(20).mean().iloc[-1]), 2),
        "ma60": round(float(c.rolling(60).mean().iloc[-1]), 2) if len(d) > 60 else None,
        "vol_ratio": round(float(d["volume"].iloc[-1] / d["volume"].rolling(20).mean().iloc[-1]), 2),
        "atr_pct": round(float((d["high"] - d["low"]).rolling(14).mean().iloc[-1] / c.iloc[-1] * 100), 2),
        "high20": round(float(c.rolling(20).max().iloc[-1]), 2),
        "low20": round(float(c.rolling(20).min().iloc[-1]), 2),
        "dd_from_high20": round(float((c.iloc[-1] / c.rolling(20).max().iloc[-1] - 1) * 100), 2),
        "pos_in_20": round(float((c.iloc[-1] - c.rolling(20).min().iloc[-1]) /
                                 (c.rolling(20).max().iloc[-1] - c.rolling(20).min().iloc[-1])), 3),
    }
    return snap


# ---------------- ② 决策树闸门（PA_Agent 二元决策思路的规则化实现） ----------------

def decision_gates(s: dict) -> dict:
    """四道闸门，输出策略路径（模仿 PA_Agent 的决策树路由）"""
    gates = {}
    gates["G1_趋势"] = "多头(价>MA20)" if s["close"] > s["ma20"] else "空头(价<MA20)"
    gates["G2_动量"] = "动量向上(ret5>0)" if (s.get("ret_5d") or 0) > 0 else "动量向下/平"
    gates["G3_量能"] = "放量(量比>1.2)" if s["vol_ratio"] > 1.2 else ("缩量(量比<0.8)" if s["vol_ratio"] < 0.8 else "量能平稳")
    gates["G4_风险"] = f"回撤风险可控(距高点{abs(s['dd_from_high20']):.1f}%)" if s["dd_from_high20"] > -8 else f"高位风险(距高点回撤{s['dd_from_high20']:.1f}%)"

    # 路由规则
    if gates["G1_趋势"].startswith("多") and gates["G2_动量"].startswith("动") and gates["G3_量能"].startswith("放"):
        path = "趋势+动量+放量 → 进攻型策略"
    elif gates["G1_趋势"].startswith("多") and not gates["G3_量能"].startswith("放"):
        path = "趋势多头但量能不足 → 观望等待放量确认"
    elif gates["G1_趋势"].startswith("空"):
        path = "空头趋势 → 回避或只做防守"
    else:
        path = "震荡格局 → 轻仓试探/等待突破"
    return {"gates": gates, "path": path}


# ---------------- ③ 两阶段 LLM 分析 ----------------

STAGE1_SYSTEM = (
    "你是专业的价格行为(Price Action)分析师。根据个股K线数据快照，判断当前市场结构和交易机会。"
    "只输出JSON: {\"structure\":\"趋势/震荡/回调/突破\",\"quality\":0-100,"
    "\"key_levels\":\"关键价位\",\"reason\":\"一句话依据\"}"
)

STAGE2_SYSTEM = (
    "你是交易决策助手。结合结构诊断和决策树闸门结果，给出明确交易计划。"
    "只输出JSON: {\"action\":\"买入/卖出/观望\",\"entry\":\"入场条件\","
    "\"stop\":\"止损位\",\"position\":\"仓位建议\",\"risk_note\":\"风险提示\"}"
)


def load_experience(limit: int = 3) -> str:
    """经验库：最近几次分析结论，供 LLM 参考"""
    if not os.path.exists(EXPERIENCE_FILE):
        return "（暂无历史经验）"
    try:
        with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
            rows = json.load(f)
        recent = rows[-limit:]
        return "；".join(f"{r['code']}@{r['date']}: {r.get('path','?')}->{r.get('stage2','?')}" for r in recent)
    except Exception:
        return "（经验库读取失败）"


def run_analysis(code: str, days: int = 120) -> dict:
    cfg = load_llm_config()
    snap = build_snapshot(code, days)
    gates = decision_gates(snap)

    if not cfg["api_key"]:
        result = {"mode": "规则模式(未配置Key)", **snap, **gates,
                  "note": "未配置 API Key，仅输出客观数据与闸门路由"}
    else:
        # Stage 1: 结构诊断
        user1 = (
            f"代码:{code} 日期:{snap['date']} 收盘:{snap['close']} "
            f"近1日:{snap['ret_1d']}% 近5日:{snap['ret_5d']}% "
            f"MA5/20/60:{snap['ma5']}/{snap['ma20']}/{snap['ma60']} "
            f"量比:{snap['vol_ratio']} ATR%:{snap['atr_pct']} "
            f"20日区间位置:{snap['pos_in_20']} 距高点:{snap['dd_from_high20']}% "
            f"关键位: 20日高{snap['high20']} / 低{snap['low20']}"
        )
        stage1 = call_llm(cfg, STAGE1_SYSTEM, user1)

        # Stage 2: 交易决策（带闸门路径 + 经验库）
        exp = load_experience()
        user2 = (
            f"结构诊断:{stage1}\n"
            f"决策树闸门: {' | '.join(gates['gates'].values())}\n"
            f"路由结论: {gates['path']}\n"
            f"历史经验参考: {exp}\n"
            f"请给出明确交易计划。"
        )
        stage2 = call_llm(cfg, STAGE2_SYSTEM, user2)

        result = {"mode": "LLM模式", **snap, **gates, "stage1": stage1, "stage2": stage2}

    # 落盘 + 经验库
    with open(os.path.join(OUTPUT_DIR, "pa_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    try:
        with open(EXPERIENCE_FILE, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    rows.append({"code": code, "date": snap["date"], "path": gates["path"],
                 "stage2": result.get("stage2", result.get("note", ""))})
    rows = rows[-50:]
    with open(EXPERIENCE_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="600519", help="股票代码")
    parser.add_argument("--days", type=int, default=120, help="分析窗口（交易日）")
    args = parser.parse_args()
    result = run_analysis(args.code, args.days)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
