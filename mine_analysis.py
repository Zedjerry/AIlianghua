# -*- coding: utf-8 -*-
"""
mine_analysis.py — 挖矿结果 AI 解读（AlphaMaster alphagpt 功能的实现）
=====================================================================
训练结束后，用 LLM 解读挖出的因子公式：
    ① 公式逐步解读（每个算子/特征的含义与组合逻辑）
    ② 训练质量评估（分数/IC/暴露度代表什么）
    ③ 应用建议与风险（适合什么市场环境、怎么用）

用法:
    python mine_analysis.py --formula formulas/600519_formula.json
    python mine_analysis.py                              # 默认最新公式

输出:
    output/mine_analysis.json   （webui 挖矿页展示）
"""

import argparse
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_llm.json")
OUTPUT_DIR = "output"
FORMULA_DIR = "formulas"
os.makedirs(OUTPUT_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "你是量化因子研究专家，擅长解读机器学习挖出的技术因子公式。"
    "用户会给你一个因子公式（算子序列）和训练统计。请输出JSON，格式: "
    "{\"step_interpret\":\"逐步解释公式中每个算子的含义和整体逻辑\","
    "\"quality\":\"训练质量评估：分数/IC/暴露度说明什么\","
    "\"usage\":\"这个因子适合什么市场环境、怎么用\","
    "\"risks\":\"主要风险与失效场景\"}"
)


def load_llm_config() -> dict:
    cfg = {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash",
           "api_key": os.environ.get("QUANT_LLM_API_KEY", ""), "timeout": 90}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if v})
    return cfg


def call_llm(cfg: dict, user: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=cfg["timeout"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


def latest_formula() -> str:
    """没有指定文件时，取 formulas/ 里分数最高的公式"""
    best, best_score = None, -1e9
    for f in os.listdir(FORMULA_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(FORMULA_DIR, f), "r", encoding="utf-8") as fp:
                    s = json.load(fp)
                sc = float(s.get("best_score", 0))
                if sc > best_score:
                    best, best_score = os.path.join(FORMULA_DIR, f), sc
            except Exception:
                pass
    return best


def run_analysis(formula_path: str) -> dict:
    with open(formula_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    decoded = spec.get("formula_decoded", "?")
    score = spec.get("best_score", "?")
    symbol = spec.get("symbol", "?")
    steps = spec.get("train_step", "?")

    cfg = load_llm_config()
    user = (
        f"标的:{symbol} 训练步数:{steps} 最优验证分数:{score}\n"
        f"公式: {decoded}\n"
        f"请解读这个因子公式。"
    )
    if not cfg["api_key"]:
        analysis = json.dumps({"step_interpret": "未配置API Key，无法调用LLM解读",
                               "quality": f"分数 {score}", "usage": "配置config_llm.json后启用",
                               "risks": "-"}, ensure_ascii=False)
    else:
        analysis = call_llm(cfg, user)

    result = {"file": os.path.basename(formula_path), "symbol": symbol,
              "decoded": decoded, "score": score, "analysis": analysis}
    with open(os.path.join(OUTPUT_DIR, "mine_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", default=None, help="公式 JSON 路径（默认取分数最高者）")
    args = parser.parse_args()
    path = args.formula or latest_formula()
    if not path or not os.path.exists(path):
        raise SystemExit("没有可用公式，请先运行 mine_factor.py 挖矿")
    print(f"解读公式: {path}", flush=True)
    result = run_analysis(path)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
