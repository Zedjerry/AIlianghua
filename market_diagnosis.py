# -*- coding: utf-8 -*-
"""
market_diagnosis.py — 市场诊断层（吸收 PA_Agent 两阶段 LLM 决策的优点）
======================================================================
在每日信号生成后，用大模型做"市场诊断 → 交易决策建议"，作为选股信号的
环境闸门与仓位调节器（只建议、不下单，与 PA_Agent 口径一致）。

两阶段（PA_Agent 风格）:
    Stage1 市场诊断: 输入今日市场状态（指数/宽度/量能/信号分布）
            → LLM 输出市场环境（趋势/震荡/风险）与把握度
    Stage2 交易决策: 结合今日 Top 信号与诊断 → 输出交易建议
            （正常交易/轻仓/观望 + 仓位系数 + 风险提示）

无 Key 时自动降级为"规则模式"（不改变任何交易，仅输出客观诊断文本）。

配置:
    首次运行生成 config_llm.json，填入 base_url / model / api_key；
    也支持环境变量 QUANT_LLM_API_KEY。

用法:
    python market_diagnosis.py --demo        # 用今日数据演示（无 Key 也能跑）
"""

import json
import os
from datetime import datetime

import pandas as pd

DATA_DIR = "data"
OUTPUT_DIR = "output"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_llm.json")


# ---------------- 配置 ----------------

def load_config() -> dict:
    cfg = {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_key": os.environ.get("QUANT_LLM_API_KEY", ""),
        "timeout": 60,
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if v})
    return cfg


def ensure_config_template():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"base_url": "https://api.deepseek.com",
                       "model": "deepseek-v4-flash",
                       "api_key": ""}, f, ensure_ascii=False, indent=2)
        print(f"[提示] 已生成配置模板 {CONFIG_FILE}，填入 api_key 后即可启用 LLM 诊断", flush=True)


# ---------------- 市场状态汇总 ----------------

def build_market_snapshot() -> dict:
    """从我们的数据汇总今日市场状态（全部客观指标）"""
    daily = pd.read_csv(os.path.join(DATA_DIR, "stock_daily.csv"), dtype={"code": str})
    idx = pd.read_csv(os.path.join(DATA_DIR, "index_000300.csv"))
    idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")

    snap = {"date": daily["date"].max(), "index_trend": None, "advance_ratio": None,
            "strong_count": None, "amount_ratio": None, "top_signals": []}

    # 沪深300 近 5 日表现
    idx = idx.sort_values("date")
    if len(idx) >= 6:
        last5 = idx.tail(6)
        snap["index_trend"] = round((last5["close"].iloc[-1] / last5["close"].iloc[0] - 1) * 100, 2)

    # 市场宽度（当日）
    d = daily[daily["date"] == snap["date"]].copy()
    if not d.empty:
        d["ret"] = d["close"] / d["open"] - 1
        snap["advance_ratio"] = round((d["ret"] > 0).mean() * 100, 1)
        snap["strong_count"] = int((d["ret"] >= 0.03).sum())
        prev = daily[daily["date"] < snap["date"]]["amount"].sum()
        snap["amount_ratio"] = round(d["amount"].sum() / prev, 2) if prev else None

    # 今日信号 Top5
    sig = pd.read_csv(os.path.join(OUTPUT_DIR, "signals_today.csv"), dtype={"code": str})
    if sig is not None and not sig.empty:
        top = sig.sort_values("pred_5d_return", ascending=False).head(5)
        snap["top_signals"] = [
            {"code": r.code, "name": getattr(r, "name", ""),
             "pred_pct": round(float(getattr(r, "pred_5d_return", 0)) * 100, 2)}
            for r in top.itertuples()
        ]
    return snap


# ---------------- LLM 调用（两阶段） ----------------

STAGE1_SYSTEM = (
    "你是A股量化交易的市场诊断助手。根据给出的客观市场数据，判断当前市场环境。"
    "只输出JSON，格式: {\"regime\":\"趋势上涨|震荡|趋势下跌|风险\",\"confidence\":0-100,\"reason\":\"一句话理由\"}"
)

STAGE2_SYSTEM = (
    "你是A股量化策略的风控参谋。结合市场诊断结果和今日选股信号，给出交易建议。"
    "只输出JSON，格式: {\"action\":\"正常交易|轻仓|观望\",\"position_scale\":0-1,\"risk_note\":\"一句话风险提示\"}"
)


def _call_llm(cfg: dict, system: str, user: str):
    from openai import OpenAI
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg["timeout"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def run_diagnosis() -> dict:
    cfg = load_config()
    snap = build_market_snapshot()
    ensure_config_template()

    if not cfg["api_key"]:
        # 规则降级：输出客观诊断文本，不做任何决策改动
        result = {
            "mode": "规则模式(未配置Key)",
            "date": snap["date"],
            "index_5d_pct": snap["index_trend"],
            "advance_ratio": snap["advance_ratio"],
            "note": "未配置 API Key，本层不干预交易。填写 config_llm.json 的 api_key 后启用 LLM 诊断。",
        }
    else:
        # Stage 1: 市场诊断
        user1 = (
            f"日期:{snap['date']} 沪深300近5日涨跌:{snap['index_trend']}% "
            f"上涨家数占比:{snap['advance_ratio']}% 强势股(涨幅≥3%)家数:{snap['strong_count']} "
            f"成交额倍率:{snap['amount_ratio']}"
        )
        stage1 = _call_llm(cfg, STAGE1_SYSTEM, user1)

        # Stage 2: 交易决策
        top_text = "、".join(f"{s['name']}({s['code']},预测+{s['pred_pct']}%)" for s in snap["top_signals"])
        user2 = (
            f"市场诊断结果:{stage1}\n"
            f"今日选股信号Top5:{top_text}\n请给出交易建议。"
        )
        stage2 = _call_llm(cfg, STAGE2_SYSTEM, user2)

        result = {"mode": "LLM模式", "date": snap["date"], "stage1": stage1, "stage2": stage2}

    # 落盘，供 webui 展示
    try:
        with open(os.path.join(OUTPUT_DIR, "diagnosis.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="演示模式（无Key也能跑）")
    args = parser.parse_args()
    result = run_diagnosis()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
