"""
lab3_prefix_cache.py —— KV Cache / 前缀缓存的成本账：为什么「前缀必须逐字节稳定」
=====================================================================================
对应《深入理解 AI Agent》2.3 节（p50）：上下文管理，以及
2.3.2 KV Cache 的原理与约束（p55）、2.3.3 KV Cache 与 Prompt Cache 两个层级（p57）、
2.3.4 缓存作为架构约束（p57）。

一句话原理：
    模型处理上下文时，每读一个 token 都要算一份 KV（注意力缓存的键值对）。
    如果这次请求的开头和上次**一模一样**（逐字节相同），服务端就能直接复用上次算好的
    KV，这段就不重复计算、也不按全价计费 —— 这就是前缀缓存 / Prompt Cache。
    一旦中间任何一个字节变了，**从变的位置往后全部作废**（KV 是前缀式的，不能跳过）。

本实验模拟 20 轮 Agent 会话，比较 5 种上下文管理策略的命中率与账单：
    A 静态前缀逐字节稳定（工具定义固定在系统提示词之后，永不改动）
    B 在前缀里插入「当前时间戳」——每轮都不一样
    C 每轮把历史消息重排/重写后拼进前缀——字节全变
    D 工具 schema 按需动态追加到上下文**末尾**（书中 2.3 节提到的 2026 生产框架做法）
    E 工具 schema 按需插入到历史**之前**（D 的反面教材，位置错了）

计价（示意）：命中 $0.1 / 百万 token，未命中 $1.0 / 百万 token。运行：python lab3_prefix_cache.py
=====================================================================================
"""

import json
import sys

from mockllm import count_messages_tokens, count_tokens, pad

if not sys.stdout.isatty():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

# ------------------------------------------------------------------ 计价与规模
MISS_PRICE = 1.0                      # 未命中：$1 / 百万 token
HIT_PRICE = 0.1                       # 命中：$0.1 / 百万 token（便宜 10 倍）
TURNS = 20                            # 会话轮数
SYSTEM_PROMPT = ("你是运维排障助手。每轮先用工具确认事实，再给出结论；"
                 "不要凭记忆猜测端口、版本和错误码。")
TOOL_DEFS = [                              # 真实系统里工具 schema 是前缀中最占地方的部分
    {"type": "function", "function": {
        "name": "run_shell", "description": "在受控环境执行只读命令并返回标准输出",
        "parameters": {"type": "object", "properties": {
            "cmd": {"type": "string", "description": "要执行的命令，仅允许只读命令"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 30"}},
            "required": ["cmd"]}}},
    {"type": "function", "function": {
        "name": "query_metrics", "description": "按指标名与时间窗口查询监控指标",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "description": "指标名，如 latency_p99"},
            "window": {"type": "string", "description": "时间窗口，如 1h / 24h"},
            "group_by": {"type": "string", "description": "可选的聚合维度"}},
            "required": ["metric", "window"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "读取指定路径的文本文件内容",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "文件的绝对路径"},
            "max_lines": {"type": "integer", "description": "最多读取的行数"}},
            "required": ["path"]}}}]
TOOLS_SCHEMA = json.dumps(TOOL_DEFS, ensure_ascii=False)

# 20 轮会话的素材：一个 Agent 排查「订单服务超时」的完整过程
STEPS = ["检查配置文件里的端口设置", "查看服务最近 50 行错误日志", "统计各接口的平均延迟",
         "核对数据库连接池上限", "检查缓存的命中率", "查询上游支付网关的响应时间",
         "查看线程池的排队长度", "比对灰度版本与线上版本的差异", "统计超时请求的地域分布",
         "确认最近一次发布的变更内容"]
OBS = ["配置文件监听端口 = 8080，正常", "日志末尾出现 12 次 connection reset",
       "订单接口 P99 = 2.4s，超过 1s 预算", "连接池上限 = 20，当前占用 19",
       "缓存命中率 = 61%，低于 90% 的基线", "支付网关 P95 = 1.8s，比上周慢了 3 倍",
       "线程池队列长度 = 340，持续增长", "灰度版本多了 1 个同步调用，线上没有",
       "超时请求集中在两个可用区", "变更内容：新增了同步写入审计日志"]

def make_turns(n=TURNS):
    """造 n 轮会话，每轮 3 条消息：用户提问 → 模型回复（带工具调用）→ 工具结果。"""
    turns = []
    for i in range(1, n + 1):
        step, obs = STEPS[(i - 1) % len(STEPS)], OBS[(i - 1) % len(OBS)]
        turns.append([
            {"role": "user", "content": "第 %d 步：%s。" % (i, step)},
            {"role": "assistant", "reasoning": "先确认「%s」的实际情况，再决定下一步。" % step,
             "content": "已执行检查：%s。" % step,
             "tool_calls": [{"name": "run_shell", "args": {"cmd": "check " + str(i)}}]},
            {"role": "tool", "name": "run_shell", "content": obs},
        ])
    return turns

TU = make_turns()
SYS_TOK = count_messages_tokens([{"role": "system", "content": SYSTEM_PROMPT}])
TOOLS_TOK = count_tokens(TOOLS_SCHEMA)

def msg_tokens(msgs): return count_messages_tokens(msgs)

# ------------------------------------------------------------------ 5 种策略
# 上下文 = 一串「段」，段用 (key, tokens) 表示。key 是这个段内容的指纹：
# key 相同 = 字节相同 = 可以命中缓存；key 不同 = 从这一段开始全部作废。
def segments(strategy, turn):
    """返回第 turn 轮请求的分段列表。历史部分对 A/C/D/E 内容相同。"""
    head = [("系统提示词", SYS_TOK)]
    tools_seg = ("工具定义", TOOLS_TOK)
    history = []                                    # 逐条消息（字节稳定的写法）
    for i in range(1, turn + 1):
        for m in TU[i - 1][:1 if i == turn else 3]:  # 最后一轮只到新来的用户消息
            history.append(("msg-%s-%d" % (m["role"], i), msg_tokens([m])))
    if strategy == "A":                             # 逐字节稳定：静态前缀 + 逐条追加
        return head + [tools_seg] + history
    if strategy == "B":                             # 时间戳插在系统提示词之后
        ts = "当前时间：2026-03-15 14:%02d:%02d" % (turn, (turn * 7) % 60)
        return head + [("时间戳-" + ts, count_tokens(ts))] + [tools_seg] + history
    if strategy == "C":                             # 历史重排/重写：整块换成一个新段
        total = sum(t for _k, t in history)
        return head + [tools_seg] + [("重排后的历史@%d" % turn, total)]
    if strategy == "D":                             # 工具 schema 追加到末尾（内容每轮可能不同）
        dyn = TOOLS_SCHEMA + (' // 本轮按需加载：turn=%d' % turn)
        return head + history + [("按需工具-" + str(turn), count_tokens(dyn))]
    if strategy == "E":                             # 工具 schema 插在历史之前
        dyn = TOOLS_SCHEMA + (' // 本轮按需加载：turn=%d' % turn)
        return head + [("按需工具-" + str(turn), count_tokens(dyn))] + history
    raise ValueError("未知策略：%s" % strategy)

def common_prefix_tokens(prev, cur):
    """前缀缓存的命中长度 = 两次请求最长公共前缀的 token 数（逐段比对，段内前缀不算）。"""
    hit = 0
    for (kp, tp), (kc, _tc) in zip(prev, cur):
        if kp != kc:
            break
        hit += tp
    return hit

def simulate(strategy):
    prev, total_in, total_hit, detail = None, 0, 0, []
    for turn in range(1, TURNS + 1):
        cur = segments(strategy, turn)
        n = sum(t for _k, t in cur)
        hit = 0 if prev is None else common_prefix_tokens(prev, cur)     # 第 1 轮没有缓存
        total_in += n
        total_hit += hit
        detail.append((turn, n, hit, (n - hit) * MISS_PRICE + hit * HIT_PRICE))
        prev = cur
    miss = total_in - total_hit
    cost = (miss * MISS_PRICE + total_hit * HIT_PRICE) / 1e6
    return {"strategy": strategy, "input": total_in, "hit": total_hit, "miss": miss,
            "rate": total_hit / total_in, "cost": cost, "detail": detail}

NAMES = {"A": "A 静态前缀稳定", "B": "B 前缀插时间戳", "C": "C 历史重排重写",
         "D": "D 工具追加末尾", "E": "E 工具插在中间"}
MAIN = ["A", "B", "C"]
VARIANT = ["D", "E"]

def print_table(results):
    print("-" * 92)
    print(pad("策略", 20) + pad("总输入token", 14) + pad("命中token", 12) + pad("未命中token", 14)
          + pad("命中率", 10) + pad("本轮会话成本", 16) + "相对 A 的倍数")
    print("-" * 92)
    base = results[0]["cost"]
    for r in results:
        print(pad(NAMES[r["strategy"]], 20) + pad(str(r["input"]), 14) + pad(str(r["hit"]), 12)
              + pad(str(r["miss"]), 14) + pad("%.1f%%" % (r["rate"] * 100), 10)
              + pad("$%.6f" % r["cost"], 16) + "%.2fx" % (r["cost"] / base))
    print("-" * 92)

def bar_chart(results, width=44):
    """ASCII 柱状图：柱子长度按成本等比缩放。"""
    print("\n【成本对比柱状图】每格 ≈ 最大成本的 1/%d" % width)
    worst = max(r["cost"] for r in results)
    for r in results:
        n = max(1, int(round(r["cost"] / worst * width)))
        print(pad(NAMES[r["strategy"]], 20) + "|" + "█" * n + " $%.6f" % r["cost"])

def main():
    print("=" * 92)
    print("lab3 前缀缓存成本账：同一个 20 轮会话，只改「上下文怎么拼」，账单差好几倍")
    print("系统提示词 %d tokens，工具定义 %d tokens，20 轮共新增轨迹 %d 条消息"
          % (SYS_TOK, TOOLS_TOK, sum(len(t) for t in TU)))
    print("计价：命中 $0.1/百万 token，未命中 $1.0/百万 token（命中便宜 10 倍）")
    print("=" * 92)

    results = [simulate(s) for s in MAIN]
    print_table(results)
    bar_chart(results)

    print("\n【为什么差这么多：抽出几个轮次看命中长度】")
    print(pad("轮次", 8) + pad("策略A 命中", 14) + pad("策略B 命中", 14) + pad("策略C 命中", 14)
          + "说明")
    for t in (1, 2, 5, 10, 20):
        a, b, c = (simulate(s)["detail"][t - 1] for s in MAIN)
        print(pad(str(t), 8) + pad(str(a[2]), 14) + pad(str(b[2]), 14) + pad(str(c[2]), 14)
              + "A 每轮只新增的内容要付费，B/C 从改动点往后全部重算")
    print("""
逐条解读：
1. 策略 A：父上下文逐字节不变，新内容只追加在末尾。第 t 轮命中长度 ≈ 第 t-1 轮的
   全部输入，只有本轮新加的消息是「未命中」——所以命中率接近九成，账单最低。
2. 策略 B：时间戳插在系统提示词之后。系统提示词之后的每一个 token（含 %d 个工具定义
   和整段历史）在每轮都因为「位置变了」而作废，命中长度恒等于系统提示词的 %d 个 token。
   明明只是插了个时间，账单却涨了好几倍。
3. 策略 C：历史被重排/重写后再拼进前缀，整段历史的字节都变了 —— 每轮能命中的只剩
   静态前缀那 %d 个 token（系统提示词 %d + 工具定义 %d），历史再长也复不上一分钱。
   这两条是本实验最反直觉的地方：**你看不见的字节变化，账单看得见。**""" % (
        TOOLS_TOK, SYS_TOK, SYS_TOK + TOOLS_TOK, SYS_TOK, TOOLS_TOK))

    print("\n" + "=" * 92)
    print("结论：前缀必须逐字节稳定。缓存不是「尽量复用」，而是「一模一样才复用」。")
    print("      所以生产框架会把上下文严格分层：")
    print("        第 1 层（永久不变）系统提示词 + 工具定义 → 全量命中")
    print("        第 2 层（只增长）  用户消息 / 模型回复 / 工具结果，按时间顺序追加 → 全量命中")
    print("        第 3 层（每轮可变）时间戳、动态检索结果、临时状态 → 放到最末尾")
    print("      任何「看起来无关紧要」的小改动（插时间、重排、重写），只要动了前面的字节，")
    print("      后面所有缓存全部失效 —— 这就是 2.3.4 说的「缓存不是优化项，而是架构约束」。")

    print("\n【变体讨论：把工具 schema 动态加载，会不会破坏前缀缓存？】")
    print("书中 2.3 节提到，2026 年以来的生产框架不再把全部工具定义固定在前缀里，")
    print("而是按需把相关工具的完整 schema 动态加载进来。关键不在于「动态」，而在于「加在哪」。")
    variants = [results[0]] + [simulate(s) for s in VARIANT]
    r0 = {x["strategy"]: x for x in variants}         # 命中率/成本，供下面的文字使用
    print_table(variants)
    print("""D 工具追加到末尾：上一轮的静态前缀和历史原封不动地被新请求当作前缀，所以历史部分
   仍然全部命中；代价是刚追加的那个动态尾巴（约 %d tokens）每轮都要重新计算，
   命中率 %.1f%%（A 是 %.1f%%），账单约 2 倍 —— 远好于 E。
E 工具插在历史之前：位置一动，后面的历史全部作废，命中率直接掉到 B 的水平。
   同一份工具 schema，放末尾和放中间，账单差 %.1f 倍 —— 位置决定命运。""" % (
        TOOLS_TOK, r0["D"]["rate"] * 100, r0["A"]["rate"] * 100,
        r0["E"]["cost"] / r0["D"]["cost"]))

    print("\n" + "=" * 92)
    print("【思考题】")
    print("1. 如果确实需要在上下文里带上当前时间，怎么放才能既满足需求又不打掉缓存？")
    print("2. 你的 Agent 每轮都要检索一次知识库，检索结果该放在上下文的哪个位置？")
    print("3. 上下文压缩（lab4）会重写历史，它和前缀缓存冲突吗？冲突时怎么权衡？")
    print("=" * 92)

    # ----------------------------- 可验证的断言 -----------------------------
    r = {x["strategy"]: x for x in variants}          # variants = A / D / E
    r.update({x["strategy"]: x for x in results})     # 再补上 B / C
    assert r["A"]["rate"] > 0.80, "稳定前缀的命中率应该很高"
    assert r["B"]["rate"] < 0.20, "插入时间戳后命中率应该崩掉"
    assert r["C"]["rate"] < 0.30, "重排历史后只剩静态前缀能命中"
    assert r["B"]["cost"] > r["A"]["cost"] * 3, "B 的账单应显著高于 A"
    assert r["D"]["rate"] > 0.65, "追加到末尾不应破坏前缀缓存（只是尾巴要重算）"
    assert r["E"]["rate"] < 0.10, "插到中间应该把历史缓存全部打掉"
    assert r["E"]["cost"] > r["D"]["cost"] * 2, "位置不同，账单应该差出量级"
    print("断言全部通过 ✓：A 命中 %.1f%%、B %.1f%%、C %.1f%%；追加到末尾 D %.1f%%（比 A 贵 %.1f 倍），"
          "插到中间 E %.1f%%（比 D 贵 %.1f 倍）"
          % (r["A"]["rate"] * 100, r["B"]["rate"] * 100, r["C"]["rate"] * 100, r["D"]["rate"] * 100,
             r["D"]["cost"] / r["A"]["cost"], r["E"]["rate"] * 100, r["E"]["cost"] / r["D"]["cost"]))

if __name__ == "__main__":
    main()
