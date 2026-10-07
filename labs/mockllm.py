"""
mockllm.py —— 离线教学用的「假 LLM」（Mock LLM）
==========================================================================
本文件**不是**真的语言模型，也不联网。它是一个「规则 + 模板」驱动的**教学替身**：输入上下文
（messages）和可用工具（tools），按写死的规则吐出结构化决策，返回结构与真实 LLM 完全一致：
    {"reasoning": str, "content": str, "tool_calls": [{"name": ..., "args": {...}}]}

为什么教学要用替身：① 零配置、零网络、可复现（真实 API 要 key、要花钱、还有随机性）；② Agent
的原理（组装上下文 → 模型决策 → 工具执行 → 结果回填）与「模型是谁」无关；③ 替身不会「涌现」，
行为完全由规则决定——解释「能力来自参数而非提示词」时反而比真模型更容易说清楚。替身足以把
ReAct 循环、上下文消融、前缀缓存、压缩策略全部跑通。
真实场景怎么替换：把 `MockLLM.chat()` 换成任意一家 API 客户端即可，接口保持不变（messages + tools
进去，reasoning/content/tool_calls 出来）。

policy（行为模式）——用于消融实验：故意弄坏模型/上下文的某一部分，看 Agent 怎么退化。
    normal          正常：按 ReAct 循环推进（换算 → 汇总 → 回答）
    no_tool_defs    看不到工具定义 → 无法调用任何工具，只能凭常识瞎估
    no_reasoning    思考过程为空 → 决策不连贯：一次只处理一个币种、还会漏算
    no_history      每次只看最后一条消息 → 重复操作，任务推不动
    no_tool_result  工具结果没进上下文 → 盲目循环（同一条命令反复发）
    hallucinate     编造不存在的工具名（search_web / query_database）→ 工具校验失败
    loop            陷入重复：无视已有结果，反复做同一个动作
==========================================================================
"""

import re

# 各 policy 的中文说明，供实验表格直接引用
POLICIES = {
    "normal": "完整上下文，正常执行",
    "no_tool_defs": "无工具定义：看不到工具 → 无法调用工具",
    "no_reasoning": "无思考过程：决策不连贯、信息丢失",
    "no_history": "无历史记录：只看到最后一条消息 → 重复操作",
    "no_tool_result": "无工具结果：结果没回填 → 盲目循环",
    "hallucinate": "幻觉：编造不存在的工具名",
    "loop": "陷入重复：无视结果反复做同一动作",
}

# token 估算：中文（含标点、全角）1 个字 ≈ 1 token；英文/数字 4 字符 ≈ 1 token（BPE 的粗略近似）。
def _is_wide(ch: str) -> bool:
    """是否为「一个字符约等于一个 token」的宽字符（CJK 汉字、中文标点、全角符号）。"""
    code = ord(ch)
    return (0x3000 <= code <= 0x303F or 0x4E00 <= code <= 0x9FFF
            or 0xFF00 <= code <= 0xFFEF or 0x3040 <= code <= 0x30FF)

def count_tokens(text: str) -> int:
    """估算一段文本的 token 数：中文按字，英文/数字按 4 字符 1 个 token。"""
    wide = sum(1 for ch in text if _is_wide(ch))
    narrow = len(text) - wide
    return wide + (narrow + 3) // 4   # 向上取整，避免英文短串被算成 0

def render_messages(messages) -> str:
    """把 messages 列表渲染成「模型视角」的纯文本，用于计数和规则匹配。"""
    lines = []
    for m in messages:
        parts = []
        if m.get("reasoning"):
            parts.append("思考=" + str(m["reasoning"]))
        if m.get("content"):
            parts.append("内容=" + str(m["content"]))
        for call in m.get("tool_calls") or []:
            parts.append("调用=%s(%s)" % (call.get("name"), call.get("args")))
        lines.append("[%s] %s" % (m.get("role", "?"), " | ".join(parts)))
    return "\n".join(lines)

def count_messages_tokens(messages) -> int:
    """估算整段上下文 token 数：每条消息另加 4 个角色/分隔开销（真实 chat template 会包控制符）。"""
    return count_tokens(render_messages(messages)) + 4 * len(messages)

def display_width(text: str) -> int:
    """显示宽度：中文/全角算 2 格，英文算 1 格（中文是双宽字符，不处理表格就列不齐）。"""
    return sum(2 if _is_wide(ch) else 1 for ch in text)

def pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格，让中文表格的列对齐。"""
    return text + " " * max(0, width - display_width(text))

_SYMBOL_TO_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
                       "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY"}
_AMOUNT_RE = re.compile(r"([$€£¥]|USD|EUR|GBP|JPY)\s*([0-9]+(?:\.[0-9]+)?)\s*([MKmk]?)")
_SCALE = {"": 1.0, "m": 1e6, "k": 1e3}

def parse_amounts(text: str):
    """解析出 [(金额, 币种), ...]，如 '$2.5M' → (2500000.0, 'USD')：本替身只「会做」书里那个多币种收入汇总任务。"""
    out = []
    for sym, num, scale in _AMOUNT_RE.findall(text):
        out.append((float(num) * _SCALE[scale.lower()], _SYMBOL_TO_CURRENCY[sym]))
    return out

class MockLLM:
    """规则驱动的假模型。用法：llm = MockLLM(policy="normal"); d = llm.chat(msgs, tools)"""

    def __init__(self, script=None, policy="normal"):
        if policy not in POLICIES:
            raise ValueError("未知 policy: %s（可选：%s）" % (policy, list(POLICIES)))
        self.policy = policy
        self.script = list(script or [])   # 可选剧本：按顺序直接吐出预设决策
        self.calls = 0                     # 被调用次数（= Agent 的轮次）
        self._task = []                    # 教学简化：no_history 下「残存」的任务记忆

    # ------------------------------------------------------------ 对外接口
    def chat(self, messages, tools=None):
        """核心接口。messages: 上下文消息列表；tools: 工具定义列表。返回决策 dict。"""
        self.calls += 1
        tools = list(tools or [])
        visible = self._visible(messages)
        if self.script:                                     # 剧本模式（未使用则忽略）
            return self.script.pop(0)
        if self.policy == "no_tool_defs" or not tools:      # 看不到工具 → 只能瞎答
            return self._blind_answer()
        if self.policy == "hallucinate":                    # 编造工具名
            return {"reasoning": "我需要联网查一下最新汇率。", "content": "",
                    "tool_calls": [{"name": "search_web", "args": {"query": "USD EUR GBP JPY rate"}},
                                   {"name": "query_database", "args": {"table": "fx_rates"}}]}
        if self.policy == "loop":                           # 无视结果，反复做同一件事
            return {"reasoning": "再确认一次 EUR 的汇率，避免出错。", "content": "",
                    "tool_calls": [{"name": "convert_currency",
                                    "args": {"amount": 2100000.0, "from": "EUR", "to": "USD"}}]}
        if self.policy == "no_history":                     # 只看到最后一条 → 重复操作
            return self._repeat_plan(visible)
        if self.policy == "no_reasoning":                   # 没有思考过程 → 决策不连贯
            return self._incoherent(visible)
        return self._react(visible)                         # 正常 ReAct

    def summarize(self, text, max_tokens=180):
        """教学替身版「摘要」：抽取式——只留含数字/关键事实的行（真实场景应调用 LLM 生成，见 lab4）。"""
        keys = ("端口", "版本", "根因", "错误码", "结论", "配置", "依赖", "地址")
        kept = []
        for line in str(text).splitlines():
            line = line.strip()
            if line and (re.search(r"[0-9]", line) or any(k in line for k in keys)):
                kept.append(line)
        out = "【摘要】" + "；".join(kept)
        while count_tokens(out) > max_tokens and len(kept) > 1:
            kept.pop()
            out = "【摘要】" + "；".join(kept)
        return out

    # ------------------------------------------------------------ 内部：可见性
    def _visible(self, messages):
        """按 policy 模拟「模型实际能看到多少上下文」——消融实验的关键。"""
        if self.policy == "no_history":
            return list(messages[-1:])                      # 只看最后一条
        if self.policy == "no_tool_result":
            return [m for m in messages if m.get("role") != "tool"]   # 结果根本不在眼里
        return list(messages)

    # ------------------------------------------------------------ 内部：轨迹扫描
    @staticmethod
    def _scan(messages):
        """从轨迹里读出模型「已经做过什么、拿到了什么」，对应上下文工程里的状态读取。"""
        info = {"converts": [], "results": {}, "code_calls": [], "code_result": None}
        for m in messages:
            role = m.get("role")
            if role == "assistant":
                for call in m.get("tool_calls") or []:
                    name, args = call.get("name"), call.get("args") or {}
                    if name == "convert_currency":
                        info["converts"].append((args.get("from"), args.get("amount")))
                    elif name == "code_interpreter":
                        info["code_calls"].append(args.get("code", ""))
            elif role == "tool":
                text = str(m.get("content", ""))
                for frm, _to, val in re.findall(r"([A-Z]{3})->([A-Z]{3}): ([0-9.]+)", text):
                    info["results"][frm] = float(val)
                hit = re.search(r"total=([0-9.]+), mean=([0-9.]+)", text)
                if hit:
                    info["code_result"] = (float(hit.group(1)), float(hit.group(2)))
        return info

    def _task_of(self, messages):
        """取任务金额表：优先从当前可见文本解析，解析不到就用上一次记住的。"""
        found = parse_amounts(render_messages(messages))
        if found: self._task = found
        return self._task

    # ------------------------------------------------------------ 内部：各 policy 的决策
    def _blind_answer(self):
        """没有工具定义：模型不知道怎么动手，只能凭常识给一个不可信的数字。"""
        return {"reasoning": "我好像没有可用的工具，只能凭常识估计。",
                "content": "无法精确计算：我没有可用的汇率工具，粗略估计年度总收入约 960 万美元。",
                "tool_calls": []}

    def _repeat_plan(self, messages):
        """无历史记录：看不到已经做过什么，于是每轮都把同样的换算再发一遍（只记得任务开头）。"""
        task = self._task_of(messages)
        calls = [{"name": "convert_currency",
                  "args": {"amount": amt, "from": cur, "to": "USD"}}
                 for amt, cur in task if cur != "USD"]
        if not calls:                                      # 记忆为空时的兜底
            calls = [{"name": "convert_currency",
                      "args": {"amount": 2100000.0, "from": "EUR", "to": "USD"}}]
        return {"reasoning": "我需要先拿到汇率，好像还没查过。",
                "content": "", "tool_calls": calls}

    def _react(self, messages):
        """正常流程：缺汇率→换算；有汇率→算汇总；有汇总→给最终回答。"""
        task = self._task_of(messages)
        need = [(a, c) for a, c in task if c != "USD"]
        info = self._scan(messages)
        if info["code_result"]:                                    # 第三步：最终回答
            total, mean = info["code_result"]
            return {"reasoning": "换算结果和汇总结果都拿到了，可以给出最终回答。",
                    "content": "年度总收入 $%s，季度平均收入 $%s。" % (format(total, ",.2f"),
                                                                      format(mean, ",.2f")),
                    "tool_calls": []}
        missing = [(a, c) for a, c in need if c not in info["results"]]
        if not missing and need:                                   # 第二步：写代码汇总
            amounts = [(info["results"][c] if c != "USD" else a) for a, c in task]
            code = ("total = " + " + ".join("%.2f" % v for v in amounts)
                    + "\nmean = total / %d" % len(task)
                    + "\nresult = {'total': round(total, 2), 'mean': round(mean, 2)}")
            return {"reasoning": "汇率都换算好了，用代码解释器做汇总，避免心算出错。",
                    "content": "",
                    "tool_calls": [{"name": "code_interpreter", "args": {"code": code}}]}
        cur_list = "、".join(c for _a, c in missing) or "无"       # 第一步：并行换算
        return {"reasoning": "需要把 %s 换算成美元，再汇总计算。" % cur_list,
                "content": "",
                "tool_calls": [{"name": "convert_currency",
                                "args": {"amount": a, "from": c, "to": "USD"}}
                               for a, c in missing]}

    def _incoherent(self, messages):
        """无思考过程：丢掉「我打算怎么做」的中间状态——一次只换一个币种、重复换、汇总还漏算。"""
        task = self._task_of(messages)
        need = [(a, c) for a, c in task if c != "USD"]
        info = self._scan(messages)
        if info["code_result"]:                       # 拿到（错误的）汇总结果就直接回答
            total, mean = info["code_result"]
            return {"reasoning": "", "content":
                    "年度总收入 $%s，季度平均收入 $%s。" % (format(total, ",.2f"), format(mean, ",.2f")),
                    "tool_calls": []}
        missing = [(a, c) for a, c in need if c not in info["results"]]
        if missing:                                   # 一次只换算一个（不并行，效率低）
            a, c = missing[0]
            return {"reasoning": "", "content": "",
                    "tool_calls": [{"name": "convert_currency",
                                    "args": {"amount": a, "from": c, "to": "USD"}}]}
        if len(info["converts"]) <= len(need):        # 已经都换过了，却又重复换一次 EUR
            a = [amt for amt, c in need if c == "EUR"] or [need[0][0]]
            return {"reasoning": "", "content": "",
                    "tool_calls": [{"name": "convert_currency",
                                    "args": {"amount": a[0], "from": "EUR", "to": "USD"}}]}
        # 汇总时漏掉最后一种货币（JPY）——上下文里缺了推理链，聚合就丢东西
        amounts = [2500000.0] + [info["results"][c] for _a, c in need[:-1]]
        code = ("total = " + " + ".join("%.2f" % v for v in amounts)
                + "\nmean = total / %d" % len(task)
                + "\nresult = {'total': round(total, 2), 'mean': round(mean, 2)}")
        return {"reasoning": "", "content": "",
                "tool_calls": [{"name": "code_interpreter", "args": {"code": code}}]}
