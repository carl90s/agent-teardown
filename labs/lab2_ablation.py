# -*- coding: utf-8 -*-
"""
lab2_ablation.py —— 复现书里「实验 1-1：上下文的关键作用」（上下文消融）
==========================================================================
对应《深入理解 AI Agent》1.1.4 上下文：Agent 的眼睛（p20）与实验 1-1（图 1-3，p21）。
书里原表（✓ 有 / ✗ 无）：

    系统指令  工具定义  思考过程  历史记录  工具结果   结果
    完整基线    ✓        ✓        ✓        ✓        ✓        正常工作
    无工具定义  ✓        ✗        ✓        ✓        ✓        无法调用工具
    无思考过程  ✓        ✓        ✗        ✓        ✓        决策不连贯
    无历史记录  ✓        ✓        ✓        ✗        ✓        重复操作
    无工具结果  ✓        ✓        ✓        ✓        ✗        盲目循环

消融实验（Ablation Study）= 控制变量法：一次只摘掉一个组件，看系统退化成什么样。
本实验用 mockllm 的 policy 模拟「摘掉一个组件之后模型会怎么表现」。

核心洞察（本实验唯一要记住的一句话）：
    上下文决定了 Agent 能看到什么，而 Agent 只能基于它看到的信息做决策。

运行：python lab2_ablation.py
==========================================================================
"""

import json
import re
import sys

from mockllm import MockLLM, count_messages_tokens, pad

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------- 被消融的任务
SYSTEM_PROMPT = ("你是公司财务分析助手。不要心算金额：换算用 convert_currency，"
                 "汇总计算用 code_interpreter，并且必须使用工具给出的汇率。")
TOOLS = [
    {"type": "function", "function": {
        "name": "convert_currency", "description": "按内置固定汇率表换算货币",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"}, "from": {"type": "string"}, "to": {"type": "string"}},
            "required": ["amount", "from", "to"]}}},
    {"type": "function", "function": {
        "name": "code_interpreter", "description": "执行一段算术代码，结果写入变量 result",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                       "required": ["code"]}}},
]
STATIC_PREFIX = [{"role": "system", "content": SYSTEM_PROMPT}]
USER_REQUEST = {"role": "user", "content":
                "根据公司季度收入：Q1 $2.5M，Q2 €2.1M，Q3 £1.8M，Q4 ¥380M，"
                "请换算成美元并计算年度总收入与季度平均收入。"}

RATES_TO_USD = {"USD": 1.0, "EUR": 1 / 0.92, "GBP": 1 / 0.79, "JPY": 1 / 149.5}
EXPECT_TOTAL, EXPECT_MEAN = 9602895.73, 2400723.93


def exec_tool(call):
    """工具执行体。from 是 Python 关键字，所以不能写 **args 展开。"""
    name, args = call["name"], call["args"]
    if name == "convert_currency":
        amount, frm, to = float(args["amount"]), args["from"], args["to"]
        return "%s->%s: %.2f" % (frm, to, amount * RATES_TO_USD[frm] / RATES_TO_USD[to])
    if name == "code_interpreter":
        ns = {"__builtins__": {}, "round": round, "abs": abs, "sum": sum}
        exec(args["code"], ns)                                    # noqa: S102 教学沙箱
        res = ns.get("result", {})
        return "执行成功：total=%s, mean=%s" % (res.get("total"), res.get("mean"))
    return "错误：未知工具 %s" % name


def is_correct(text):
    """最终回答里的两个数字是否都对（带容差，不要直接比浮点相等）。"""
    if not text:
        return False
    nums = [float(x.replace(",", "")) for x in re.findall(r"[0-9][0-9,]*\.[0-9]{2}", text)]
    return (any(abs(n - EXPECT_TOTAL) < 1.0 for n in nums)
            and any(abs(n - EXPECT_MEAN) < 1.0 for n in nums))


# =========================================================================
# 消融运行器：四个开关分别对应「摘掉哪个组件」
#   tools=[]           摘掉工具定义（静态前缀少了一半）
#   keep_reasoning     摘掉思考过程（轨迹里不保存 reasoning）
#   policy=no_history  摘掉历史记录（模型每次只看最后一条消息）
#   append_results     摘掉工具结果（执行结果不回填进轨迹）
# =========================================================================
def run_ablation(policy, tools=None, keep_reasoning=True, append_results=True, max_rounds=8):
    llm = MockLLM(policy=policy)
    trajectory = [dict(USER_REQUEST)]
    stats = {"rounds": 0, "tool_calls": 0, "repeat_calls": 0, "unknown_calls": 0,
             "final": None, "hit_cap": False, "results_in_context": 0}
    seen = set()
    for rnd in range(1, max_rounds + 1):
        stats["rounds"] = rnd
        decision = llm.chat(STATIC_PREFIX + trajectory, TOOLS if tools is None else tools)
        trajectory.append({"role": "assistant",
                           "reasoning": decision["reasoning"] if keep_reasoning else "",
                           "content": decision["content"],
                           "tool_calls": decision["tool_calls"]})
        if not decision["tool_calls"]:                 # 没有工具调用 = 给出最终回答
            stats["final"] = decision["content"]
            break
        for call in decision["tool_calls"]:
            stats["tool_calls"] += 1
            sig = json.dumps(call, ensure_ascii=False, sort_keys=True)
            if sig in seen:                            # 完全相同的动作又做了一遍
                stats["repeat_calls"] += 1
            seen.add(sig)
            obs = exec_tool(call)
            if obs.startswith("错误"):
                stats["unknown_calls"] += 1
            if append_results:                         # ← 关掉它 = 工具结果丢失
                trajectory.append({"role": "tool", "name": call["name"], "content": obs})
    else:
        stats["hit_cap"] = True                        # for-else：没 break = 撞上轮次上限
    stats["results_in_context"] = sum(1 for m in trajectory if m.get("role") == "tool")
    stats["context_tokens"] = count_messages_tokens(trajectory)
    return stats


# =========================================================================
# 五组对照实验：顺序、符号、失败原因都照抄书里图 1-3
# check 是「实测证据是否支持书中结论」的判定条件
# =========================================================================
CONFIGS = [
    dict(name="完整基线", policy="normal", kwargs={}, mark="✓ 成功", reason="-",
         check=lambda st: is_correct(st["final"])),
    dict(name="无工具定义", policy="no_tool_defs", kwargs={"tools": []},
         mark="✗ 失败", reason="无法调用工具（上下文里没有工具定义）",
         check=lambda st: st["tool_calls"] == 0),
    dict(name="无思考过程", policy="no_reasoning", kwargs={"keep_reasoning": False},
         mark="△ 部分成功", reason="决策不连贯（重复换算 + 漏算 JPY，答案错误）",
         check=lambda st: st["repeat_calls"] > 0 and not is_correct(st["final"])),
    dict(name="无历史记录", policy="no_history", kwargs={},
         mark="△ 部分成功", reason="重复操作（每轮重做同样的换算，任务推进不下去）",
         check=lambda st: st["hit_cap"] and st["repeat_calls"] > 0
         and st["results_in_context"] > 0),
    dict(name="无工具结果", policy="no_tool_result", kwargs={"append_results": False},
         mark="✗ 失败", reason="盲目循环（结果没回填，只有重试没有进展）",
         check=lambda st: st["hit_cap"] and st["repeat_calls"] > 0
         and st["results_in_context"] == 0),
]
EXTRA = [
    dict(name="幻觉（拓展）", policy="hallucinate", kwargs={}, mark="✗ 失败",
         reason="编造不存在的工具名，被工具校验拦下", check=None),
    dict(name="陷入循环（拓展）", policy="loop", kwargs={}, mark="✗ 失败",
         reason="无视已有结果，反复做同一个动作", check=None),
]


def run_table(configs):
    rows = []
    for cfg in configs:
        stats = run_ablation(cfg["policy"], **cfg["kwargs"])
        ok = "-" if cfg["check"] is None else ("✓ 一致" if cfg["check"](stats) else "✗ 不一致")
        rows.append((cfg, stats, ok))
    print("-" * 104)
    print(pad("配置", 20) + pad("轮次", 6) + pad("工具调用", 10) + pad("重复调用", 10)
          + pad("轨迹中结果数", 14) + pad("是否成功", 12) + pad("与书中一致", 12) + "失败原因")
    print("-" * 104)
    for cfg, st, ok in rows:
        print(pad(cfg["name"], 20) + pad(str(st["rounds"]), 6) + pad(str(st["tool_calls"]), 10)
              + pad(str(st["repeat_calls"]), 10) + pad(str(st["results_in_context"]), 14)
              + pad(cfg["mark"], 12) + pad(ok, 12) + cfg["reason"])
    print("-" * 104)
    return rows


def main():
    print("=" * 104)
    print("lab2 上下文消融实验（复现书中实验 1-1）：一次只摘掉一个组件，看 Agent 怎么退化")
    print("✓ 成功 / △ 部分成功（有输出但结果不可用）/ ✗ 失败；最后一列是实测证据与书中结论是否一致")
    print("=" * 104)
    rows = run_table(CONFIGS)
    base = rows[0][1]
    print("\n【逐条解读】")
    print("1. 完整基线：%d 轮、%d 次工具调用完成任务（3 个币种并行换算 → 1 次汇总 → 回答）。"
          % (base["rounds"], base["tool_calls"]))
    print("2. 无工具定义：工具调用数 = 0。模型不是「不想」调用，而是上下文里没有工具的名字和参数格式，")
    print("   它连 convert_currency 存在都不知道 → 只能凭常识编一个约 960 万的数字（碰巧接近，但不可信）。")
    print("3. 无思考过程：模型丢了「我打算怎么做」的中间状态，变成一次只处理一个币种，还重复换算一次，")
    print("   汇总时漏掉 JPY → 答案是 $7,061,089.71（正好是书里图 1-4 只算 Q1~Q3 的那个数）。")
    print("4. 无历史记录：模型每轮只看最后一条消息，不知道「哪些币种换过了」，于是把同样三个换算反复发出去")
    print("   （重复 %d 次），任务推进不到汇总。注意轨迹里其实有 %d 条工具结果——"
          % (rows[3][1]["repeat_calls"], rows[3][1]["results_in_context"]))
    print("   结果是执行了的，只是模型看不到历史。")
    print("5. 无工具结果：轨迹里一条结果都没有（%d 条）。模型看不到「结果」，就只能一直重试——"
          % rows[4][1]["results_in_context"])
    print("   这就是生产环境里最常见的「盲目循环」。")
    print("\n  第 4、5 组的轮次和调用数完全相同，但病因完全不同：一个是「看不到历史」，一个是「看不到结果」。")
    print("  真实系统里的修复手段也完全不同：修上下文组装 vs 修结果回填。这一列数据就是区分它们的证据。")
    print("\n【拓展：另外两种退化模式】")
    run_table(EXTRA)
    print("这两组说明：上下文里「有什么」很重要，但「模型怎么用」同样重要——")
    print("幻觉来自模型侧（它编了不存在的工具），循环来自循环控制侧（缺少停止条件与结果校验）。")

    print("\n" + "=" * 104)
    print("结论：上下文决定了 Agent 能看到什么，而 Agent 只能基于它看到的信息做决策。")
    print("      就像蒙住眼睛的人做不出合理判断——看不到工具定义就不知道有哪些工具可用，")
    print("      看不到之前的执行结果就不知道已经做过什么。")
    print("=" * 104)

    # ---------------- 可验证的断言 ----------------
    bad = [c["name"] for c, _st, ok in rows if ok != "✓ 一致"]
    assert not bad, "以下配置的实测结果与书中结论不一致：%s" % bad
    assert is_correct(base["final"]), "基线必须给出正确答案"
    assert rows[1][1]["tool_calls"] == 0, "无工具定义时不应该有任何工具调用"
    assert rows[4][1]["rounds"] > base["rounds"] * 2, "无工具结果时轮次应显著多于基线"
    print("断言全部通过 ✓：5/5 配置与书中结论一致；无工具定义 0 次调用；"
          "无工具结果 %d 轮 >> 基线 %d 轮" % (rows[4][1]["rounds"], base["rounds"]))


if __name__ == "__main__":
    main()
