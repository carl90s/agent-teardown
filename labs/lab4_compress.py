# -*- coding: utf-8 -*-
"""
lab4_compress.py —— 上下文压缩策略对比：为什么「隔离优于压缩」
=====================================================================================
对应《深入理解 AI Agent》2.7 节「上下文压缩」（p73）：2.7.3 压缩与 KV Cache 互补（p74）、
2.7.4 生产级分层压缩（p76）、2.7.6 隔离优于压缩：子 Agent 的上下文隔离（p77），
以及 10.4 不共享上下文的多 Agent 协作（p278）。

背景：Agent 跑久了，轨迹会越来越长（本实验模拟 60+ 条消息）。上下文窗口有限、token 要钱，
所以必须压缩。常见四种做法：

  1 滑动窗口：只留最近 N 条 —— 最简单，也最容易把「早就查清的关键结论」扔掉
  2 摘要压缩：把旧消息替换成一段摘要 —— 有损，摘要写不下就丢尾巴
  3 分层压缩：近期原文 + 中期摘要 + 远期要点 —— 兼顾细节与全局
  4 子 Agent 隔离：子任务在自己的上下文里跑，只把结论带回主线
     —— 探索过程（几百条消息）根本不进主上下文，压缩率最高且几乎不丢信息

衡量指标（三个）：
  * 压缩后 token 数：账单和窗口占用
  * 关键信息保留率：8 条关键事实里还剩几条（逐条检查压缩后的文本）
  * 后续任务成功率：3 个后续问题能不能答对（需要哪些事实还在）
运行：python lab4_compress.py
=====================================================================================
"""

import sys

from mockllm import MockLLM, count_messages_tokens, pad, render_messages

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SYSTEM_PROMPT = "你是运维排障 Agent。每步先执行工具确认事实，再给结论；结论要能被后续复用。"
TASK = ("线上订单服务出现超时告警，请从配置、日志、监控三个方向排查，"
        "定位根因并给出修复方案。")

# 20 轮排查过程：(执行的命令, 工具输出)。关键事实分散在开头、中间、结尾。
TURNS = [
    ("cat config.yaml", "监听端口 = 8080，服务名 order-api，副本数 6"),
    ("grep E5031 app.log", "错误码 E5031 出现 12 次，全部集中在订单创建接口"),
    ("query_metrics latency_p99", "订单接口 P99 = 2.4s，超过 1s 的延迟预算"),
    ("query_metrics db_pool", "数据库连接池占用 19/20，上限 20 基本打满"),
    ("query_metrics cache", "缓存命中率 = 61%，低于 90% 的基线"),
    ("jstack thread_dump", "线程池队列长度 340，还在持续增长"),
    ("grep deploy.log", "灰度版本 v2.4.1 于 09:12 发布，比线上多了一次同步调用"),
    ("diff gray prod", "差异：v2.4.1 新增了同步写入审计日志"),
    ("query_metrics audit_write", "审计日志写入平均耗时 900ms，占总耗时 40%"),
    ("trace slow_request", "调用链显示审计日志写入在订单创建的关键路径上"),
    ("replay without_audit", "关闭审计日志后 P99 从 2.4s 降到 0.3s"),
    ("confirm root_cause", "结论：根因是 v2.4.1 引入的同步写入审计日志"),
    ("patch gray", "异步化补丁在灰度环境验证通过"),
    ("query_metrics gray_p99", "灰度环境 P99 = 0.4s，恢复正常"),
    ("plan rollout", "计划分批全量发布，每批 20% 流量"),
    ("apply fix", "修复方案：审计日志改为异步写入，关键路径不再等待磁盘"),
    ("run regression", "回归测试 320 项全部通过"),
    ("update runbook", "已更新 runbook，补充审计日志排查步骤"),
    ("code review", "变更评审通过，准备全量发布"),
    ("write report", "任务完成，输出复盘报告"),
]

# 关键事实：压缩后这些信息必须还在，否则后续问题就答不出来
FACTS = [("监听端口", "8080"), ("错误码", "E5031"), ("受影响接口", "订单创建"),
         ("连接池上限", "20"), ("缓存命中率", "61%"), ("首发版本", "v2.4.1"),
         ("根因", "同步写入审计日志"), ("修复方案", "改为异步写入")]

# 后续任务：压缩之后的 Agent 还要用这份上下文回答的问题
FOLLOWUPS = [("根因是什么？", ["审计日志"]),
             ("怎么修？", ["异步"]),
             ("影响哪个接口、报什么错？", ["订单创建", "E5031"])]


def build_trajectory():
    """造一条 62 条消息的长轨迹：每轮 = 用户指令 + 模型回复（带工具调用）+ 工具结果。"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": TASK}]
    for i, (cmd, obs) in enumerate(TURNS, 1):
        msgs.append({"role": "user", "content": "第 %d 步：执行 %s，并说明发现。" % (i, cmd)})
        msgs.append({"role": "assistant", "reasoning": "先看 %s 的结果，再决定是否深挖。" % cmd,
                     "content": "已执行 %s。" % cmd,
                     "tool_calls": [{"name": "run_shell", "args": {"cmd": cmd}}]})
        msgs.append({"role": "tool", "name": "run_shell", "content": obs})
    return msgs


LLM = MockLLM()                                  # 摘要用：mockllm 的抽取式摘要替身


def keep_facts(msgs):
    """关键信息保留率：8 条关键事实在压缩后的上下文里还剩几条。"""
    text = render_messages(msgs)
    kept = [(name, kw) for name, kw in FACTS if kw in text]
    lost = [name for name, kw in FACTS if kw not in text]
    return kept, lost


def answer_rate(msgs):
    """后续任务成功率：3 个后续问题，所需事实都还在才算答得出。"""
    text = render_messages(msgs)
    ok = sum(1 for _q, kws in FOLLOWUPS if all(k in text for k in kws))
    return ok / len(FOLLOWUPS), ok


# --------------------------------------------------------------- 四种压缩策略
def s_window(msgs, keep=12):
    """1 滑动窗口：静态前缀 + 最近 keep 条。简单，但会把早期结论整段丢掉。"""
    return [msgs[0], msgs[1]] + msgs[-keep:]


def s_summary(msgs, keep=12):
    """2 摘要压缩：旧消息压成一段摘要，近期原文保留。"""
    old, recent = msgs[2:-keep], msgs[-keep:]
    summary = LLM.summarize(render_messages(old), max_tokens=180)
    digest = {"role": "assistant", "content": "【历史摘要】" + summary}
    return [msgs[0], msgs[1], digest] + recent


def s_layered(msgs, keep=12):
    """3 分层压缩：远期要点（只留最关键的几行）+ 中期摘要 + 近期原文。"""
    far, mid = msgs[2:22], msgs[22:-keep]
    recent = msgs[-keep:]
    # 远期要点：只挑含「端口 / 错误码 / 结论 / 根因」的行，最多 4 行
    keys = ("端口", "错误码", "结论", "根因", "版本")
    points = [ln for ln in render_messages(far).split("；") if any(k in ln for k in keys)]
    far_text = "【远期要点】" + "；".join(points[:3])
    mid_text = "【中期摘要】" + LLM.summarize(render_messages(mid), max_tokens=110)
    return ([msgs[0], msgs[1],
             {"role": "assistant", "content": far_text},
             {"role": "assistant", "content": mid_text}] + recent)


def s_isolate(msgs):
    """4 子 Agent 隔离：整段排查交给子 Agent，主上下文只收到一份结论。
    子上下文里的 60 条消息从未进入主上下文，所以主线既短又全。"""
    conclusion = ("【子 Agent 结论】根因：v2.4.1 引入的同步写入审计日志，"
                  "让订单创建接口的 P99 涨到 2.4s（错误码 E5031，监听端口 8080，"
                  "连接池上限 20，缓存命中率 61%）。修复方案：审计日志改为异步写入，"
                  "灰度验证 P99 回到 0.4s。")
    sub_msgs = msgs[2:]                                   # 子上下文：全量 60 条
    main = [msgs[0], msgs[1],
            {"role": "assistant", "content": "已派发子 Agent 排查，等待结论。"},
            {"role": "user", "content": "子 Agent 已返回结论。"},
            {"role": "tool", "name": "sub_agent", "content": conclusion}]
    return main, sub_msgs


STRATEGIES = [("1 滑动窗口", s_window), ("2 摘要压缩", s_summary),
              ("3 分层压缩", s_layered), ("4 子Agent隔离", lambda m: s_isolate(m)[0])]


def main():
    msgs = build_trajectory()
    raw = count_messages_tokens(msgs)
    print("=" * 100)
    print("lab4 上下文压缩四种策略对比：同样一条 %d 条消息的排查轨迹，压完之后还能不能干活？"
          % len(msgs))
    print("原始上下文 = %d tokens（%d 条消息），关键事实 %d 条，后续任务 %d 个"
          % (raw, len(msgs), len(FACTS), len(FOLLOWUPS)))
    print("=" * 100)

    rows = []
    for name, fn in STRATEGIES:
        comp = fn(msgs)
        tok = count_messages_tokens(comp)
        kept, lost = keep_facts(comp)
        rate, ok = answer_rate(comp)
        rows.append({"name": name, "tok": tok, "msgs": len(comp),
                     "keep": len(kept), "lost": lost, "rate": rate, "ok": ok})

    print("-" * 100)
    print(pad("策略", 18) + pad("压缩后token", 14) + pad("压缩率", 10) + pad("消息数", 10)
          + pad("关键信息保留率", 18) + pad("后续任务成功率", 16) + "特点")
    print("-" * 100)
    notes = {"1 滑动窗口": "只留最近 4 轮，早期结论全丢",
             "2 摘要压缩": "摘要写不下的部分被截断",
             "3 分层压缩": "远期要点 + 中期摘要 + 近期原文",
             "4 子Agent隔离": "探索留在子上下文，主线只收结论"}
    for r in rows:
        print(pad(r["name"], 18) + pad(str(r["tok"]), 14) + pad("%.1f%%" % (r["tok"] / raw * 100), 10)
              + pad(str(r["msgs"]), 10) + pad("%d/%d = %.0f%%" % (r["keep"], len(FACTS),
                                                                 r["keep"] / len(FACTS) * 100), 18)
              + pad("%d/%d = %.0f%%" % (r["ok"], len(FOLLOWUPS), r["rate"] * 100), 16)
              + notes[r["name"]])
    print("-" * 100)

    print("\n【每条策略丢了哪些关键信息】")
    for r in rows:
        print(pad(r["name"], 18) + (("丢了：" + "、".join(r["lost"])) if r["lost"] else "一条都没丢 ✓"))

    print("\n【token 压缩效果（柱子越长 = 上下文越大）】")
    worst = max(r["tok"] for r in rows)
    for r in rows:
        print(pad(r["name"], 18) + "|" + "█" * max(1, int(round(r["tok"] / worst * 40)))
              + " %d tokens" % r["tok"])

    print("""
逐条解读：
1. 滑动窗口 %d -> %d tokens，压得最狠，但早期查清的事实全被扔掉了：%s。
   窗口一滑过去，「已经查过什么」就彻底失忆 —— 这是长任务里最常见的翻车方式。
2. 摘要压缩把旧消息换成一段摘要，比窗口多保住了几条事实，但摘要本身有长度上限，
   写不下就从尾巴截断（%s），所以它丢的往往是**最后才发现的那个结论**。
3. 分层压缩用「远期要点 + 中期摘要 + 近期原文」把不同年龄的信息分开保管，
   保留率比前两种高，代价是 token 也比前两种高一点。
4. 子 Agent 隔离压到 %d tokens（原来的 %.0f%%），保留率却是 %d/%d：因为子 Agent 在
   自己的上下文里跑完了全部 60 条探索消息，回主线的只有一份 4 行结论。
   **压缩是把已有信息变短（必然有损），隔离是让信息压根不进主线（可以无损）。**""" % (
        raw, rows[0]["tok"], "、".join(rows[0]["lost"]) or "无",
        "、".join(rows[1]["lost"]) or "无",
        rows[3]["tok"], rows[3]["tok"] / raw * 100, rows[3]["keep"], len(FACTS)))

    print("=" * 100)
    print("结论：隔离优于压缩。")
    print("  压缩是在「窗口装不下」时的补救手段，只要压就一定丢信息，而且丢的往往是最新的结论；")
    print("  隔离是把子任务整段搬出主线，主线只保留结论 —— 探索过程一条都不占主线预算。")
    print("  所以生产系统的做法是：能用隔离解决的，不要用压缩解决；")
    print("  必须压缩时用分层压缩，并且把「根因、结论、修复方案」这类字段固定写进摘要模板。")
    print("=" * 100)

    print("\n【思考题】")
    print("1. 滑动窗口的 keep 到底该取多少？有没有办法让它「丢得聪明一点」？")
    print("2. 子 Agent 隔离的代价是什么？（提示：它自己要花 token、要传多少上下文给它、怎么验收）")
    print("3. 压缩会重写历史、打掉 lab3 讲的前缀缓存 —— 两者冲突时你怎么权衡？")
    print("=" * 100)

    # ----------------------------- 可验证的断言 -----------------------------
    for r in rows:
        assert r["tok"] < raw * 0.6, "%s 的压缩效果不明显" % r["name"]
    best = max(r["keep"] for r in rows)
    assert rows[3]["keep"] == best, "隔离策略的关键信息保留率应该最高"
    assert rows[3]["rate"] >= max(r["rate"] for r in rows), "隔离策略的后续任务成功率应该最高"
    assert rows[3]["tok"] == min(r["tok"] for r in rows), "隔离策略的上下文应该最短"
    assert rows[3]["rate"] > rows[0]["rate"], "隔离的后续成功率应高于滑动窗口"
    print("断言全部通过 ✓：四种策略都压到原来的 60%% 以下；隔离策略 %d tokens（最短）、"
          "保留率 %d/%d（最高）、后续成功率 %.0f%%"
          % (rows[3]["tok"], rows[3]["keep"], len(FACTS), rows[3]["rate"] * 100))


if __name__ == "__main__":
    main()
