# -*- coding: utf-8 -*-
"""
lab1_react.py —— 亲手跑一遍 ReAct 循环
==========================================================================
对应《深入理解 AI Agent》1.1.5 ReAct 循环（p22）、2.2.3 带工具调用的多轮交互（p41）、
2.2.4 用代码实现 Agent 的核心循环（p46）。

核心事实（全书最重要的一行）：
        Agent 的上下文 = 静态前缀 + 轨迹
    静态前缀 = 系统提示词 + 工具定义（逐轮不变，可被 KV Cache 命中）
    轨迹     = user / assistant / tool 三类消息（逐轮增长，必须重新计算）

循环骨架（书里的伪代码，本文件就是它的可运行版本）：
    trajectory = [user_request]
    repeat:
        context = stable_prefix + trajectory
        decision = Model(context)          # 模型只负责"决定下一步"
        trajectory.append(decision)
        if decision 没有工具调用: return 最终回答
        for call in decision.tool_calls:   # 互不依赖的调用可以并行
            observation = Environment.execute(call)
            trajectory.append(observation)

任务（书里图 1-4 的例子）：多币种季度收入汇总
    Q1 $2.5M，Q2 €2.1M，Q3 £1.8M，Q4 ¥380M → 年度总收入、季度平均收入

运行：python lab1_react.py     （模型是 mockllm 里的教学替身，不联网、不花钱）
==========================================================================
"""

import json
import sys

from mockllm import MockLLM, count_messages_tokens, count_tokens

# 中文输出保障：输出被重定向（非终端）时用 UTF-8 编码，避免管道里出现乱码。
# 直接在终端里运行时保持系统默认（Windows 终端走 WriteConsoleW，中文正常显示）。
if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# =========================================================================
# 第一部分：静态前缀 = 系统提示词 + 工具定义
# 这两样在整个会话里**逐字节不变**，是缓存能命中的前提（见 lab3）。
# =========================================================================
SYSTEM_PROMPT = (
    "你是公司财务分析助手，负责把多币种收入统一换算成美元并做汇总。\n"
    "工作准则：\n"
    "1. 不要心算金额，换算用 convert_currency，汇总计算用 code_interpreter；\n"
    "2. 每一步都要说明你在做什么，拿到结果再决定下一步；\n"
    "3. 货币换算必须使用工具给出的汇率，不允许凭记忆编造汇率。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "convert_currency",
            "description": "按内置固定汇率表把金额从一种货币换算成另一种货币",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "待换算的金额"},
                    "from": {"type": "string", "description": "原币种，如 USD/EUR/GBP/JPY"},
                    "to": {"type": "string", "description": "目标币种，如 USD"},
                },
                "required": ["amount", "from", "to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_interpreter",
            "description": "在受限 Python 命名空间里执行一段算术代码，结果写入变量 result",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}},
                "required": ["code"],
            },
        },
    },
]

STATIC_PREFIX = [{"role": "system", "content": SYSTEM_PROMPT}]


def prefix_tokens() -> int:
    """静态前缀的 token 数 = 系统提示词的 token + 工具定义(JSON)的 token。"""
    return count_messages_tokens(STATIC_PREFIX) + count_tokens(json.dumps(TOOLS, ensure_ascii=False))


# =========================================================================
# 第二部分：Environment —— 工具的真实执行体
# 模型只负责"决定调用什么"，真正干活的是环境。换任务时改这里即可。
# =========================================================================
# 固定汇率表：1 单位外币 = 多少美元。EUR/GBP 取自 1/0.92、1/0.79，
# JPY 取自 1/149.5，这样能复现书里图 1-4 的 EUR->USD 2,282,608.70 等数字。
RATES_TO_USD = {"USD": 1.0, "EUR": 1 / 0.92, "GBP": 1 / 0.79, "JPY": 1 / 149.5}


def convert_currency(amount, frm, to):
    """把 amount 从 frm 换算成 to（先折美元再折目标币种），返回一行文本观察结果。"""
    usd = float(amount) * RATES_TO_USD[frm]
    return "%s->%s: %.2f" % (frm, to, usd / RATES_TO_USD[to])


def code_interpreter(code):
    """在受限命名空间里执行代码（真的算，不是假算）。禁用 __builtins__ 以防乱来。"""
    safe_ns = {"__builtins__": {}, "round": round, "abs": abs, "sum": sum, "min": min, "max": max}
    exec(code, safe_ns)                       # noqa: S102 —— 教学用受限沙箱，仅允许算术
    res = safe_ns.get("result", {})
    return "执行成功：total=%s, mean=%s" % (res.get("total"), res.get("mean"))


def _exec_tool(call):
    """按工具名分发到真实实现。注意 from 是 Python 关键字，不能写成 **args 直接展开。"""
    name, args = call["name"], call["args"]
    if name == "convert_currency":
        return convert_currency(args["amount"], args["from"], args["to"])
    if name == "code_interpreter":
        return code_interpreter(args["code"])
    return "错误：未知工具 %s" % name

USER_REQUEST = {
    "role": "user",
    "content": ("根据公司季度收入：Q1 $2.5M，Q2 €2.1M，Q3 £1.8M，Q4 ¥380M，"
                "请把各季度收入换算成美元，计算公司年度总收入和季度平均收入。"),
}


# =========================================================================
# 第三部分：ReAct 主循环
# =========================================================================
def main():
    print("=" * 74)
    print("lab1 ReAct 循环：多币种收入汇总")
    print("模型：mockllm.MockLLM（规则驱动的教学替身，不是真模型，不联网、不花钱）")
    print("=" * 74)
    print("静态前缀 token 数 = %d（系统提示词 %d + 工具定义 %d）"
          % (prefix_tokens(),
             count_messages_tokens(STATIC_PREFIX),
             count_tokens(json.dumps(TOOLS, ensure_ascii=False))))
    print("静态前缀逐轮不变 → 这部分每轮都可以被 KV Cache / Prompt Cache 命中（lab3 算这笔账）\n")

    llm = MockLLM(policy="normal")
    trajectory = [USER_REQUEST]
    rounds_log = []
    final_answer = None
    max_rounds = 8                                  # 安全上限：真 Agent 也必须设，防止死循环

    for rnd in range(1, max_rounds + 1):
        traj_tokens = count_messages_tokens(trajectory)
        context = STATIC_PREFIX + trajectory        # ← 这一行就是"上下文 = 静态前缀 + 轨迹"
        print("-" * 74)
        print("第 %d 轮 | 静态前缀 %d tokens | 轨迹 %d tokens（%d 条消息）| 上下文合计 %d tokens"
              % (rnd, prefix_tokens(), traj_tokens, len(trajectory),
                 prefix_tokens() + traj_tokens))
        rounds_log.append((rnd, prefix_tokens(), traj_tokens))

        decision = llm.chat(context, TOOLS)         # 模型决策：只返回"想做什么"
        trajectory.append({"role": "assistant",
                           "reasoning": decision["reasoning"],
                           "content": decision["content"],
                           "tool_calls": decision["tool_calls"]})
        print("  [assistant.reasoning] %s" % (decision["reasoning"] or "(空)"))
        if decision["content"]:
            print("  [assistant.content  ] %s" % decision["content"])

        if not decision["tool_calls"]:              # 没有工具调用 = 任务结束
            final_answer = decision["content"]
            print("  → 模型没有发起工具调用，ReAct 循环结束。")
            break

        for call in decision["tool_calls"]:
            print("  [assistant.tool_call] %s(%s)" % (call["name"], json.dumps(call["args"], ensure_ascii=False)))
            observation = _exec_tool(call)                         # Environment 执行
            trajectory.append({"role": "tool", "name": call["name"], "content": observation})
            print("  [tool 观察结果      ] %s" % observation)
        print()

    # ---------- 结果与校验 ----------
    print("=" * 74)
    print("完整轨迹（trajectory）结构，这就是下一轮要重新喂给模型的东西：")
    print(json.dumps(trajectory, ensure_ascii=False, indent=2))
    print("=" * 74)
    expected_total, expected_mean = 9602895.73, 2400723.93
    ok = final_answer is not None and ("9,602,895.73" in final_answer) and ("2,400,723.93" in final_answer)
    print("预期答案：年度总收入 $%s，季度均值 $%s" % (format(expected_total, ",.2f"),
                                                     format(expected_mean, ",.2f")))
    print("实际答案：%s" % (final_answer or "(未完成任务)"))
    print("答案校验：%s" % ("通过 ✓" if ok else "不通过 ✗"))
    print("补充说明：书里图 1-4 展示的中间步骤只汇总了 Q1~Q3（$7,061,089.71），")
    print("          本题按完整题面把 Q4 的 ¥380M 也纳入计算，所以是 $9,602,895.73。")
    print("\n成本视角：静态前缀 %d tokens 被重复发送了 %d 次，"
          % (prefix_tokens(), len(rounds_log)))
    print("          若前缀不稳定，这部分 token 每轮都要按「未命中」全价计费（见 lab3）。")
    assert ok, "ReAct 循环没有给出正确答案，请检查 mockllm 的规则或工具实现"


if __name__ == "__main__":
    main()
