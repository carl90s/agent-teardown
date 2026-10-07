# -*- coding: utf-8 -*-
"""
lab6_eval.py —— Agent 评估：Pass@k 与 Pass^k、置信区间、LLM-as-a-Judge 的偏差
================================================================================
对应《深入理解 AI Agent》7.2.1 用 Pass@k 看能力上限（p189）、7.2.2 业务可靠性：关注
Pass^k（p189）、7.5.1 LLM-as-a-Judge（p198）、7.5.4 配对比较与模型排名（p205）、
7.7 评估结果的统计显著性（p209）。

四个实验，只用标准库 + numpy（可视化一律 ASCII）：
  1 Pass@k = 1-(1-p)^k（k 次里至少成功一次 → 能力上限）
    Pass^k = p^k      （k 次全部成功     → 业务可靠性）
    用 20000 次蒙特卡洛验证解析公式
  2 ASCII 折线图：p=0.9 时两条曲线随 k=1..10 怎么分道扬镳
  3 Wilson 95% 置信区间：为什么 benchmark 上差 2% 可能没有统计显著性
  4 LLM-as-a-Judge 的两种偏差：位置偏差（偏好第一个）和长度偏差（偏好更长的），
    以及用「配对比较 + 交换位置」把它们检测出来的办法

运行：python lab6_eval.py
================================================================================
"""

import sys

import numpy as np

from mockllm import pad

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

TRIALS = 20000
SEED = 20260101


# ------------------------------------------------------- 1 能力上限与业务可靠性
def pass_at_k(p, k):
    """解析公式：至少一次成功的概率。k 次全部失败的概率是 (1-p)^k。"""
    return 1 - (1 - p) ** k


def pass_pow_k(p, k):
    """解析公式：k 次全部成功的概率。业务上「每次都要成功」才是可靠。"""
    return p ** k


def simulate(p, k, trials=TRIALS, seed=SEED):
    """蒙特卡洛：重复 trials 次实验，每次实验连续尝试 k 遍，数成功率。"""
    rng = np.random.default_rng(seed)
    ok = rng.random((trials, k)) < p        # 每行 = 一次实验里的 k 次尝试
    return ok.any(axis=1).mean(), ok.all(axis=1).mean()


def section1():
    print("\n【实验 1】Pass@k（能力上限）与 Pass^k（业务可靠性）：解析 vs 蒙特卡洛")
    p = 0.9
    print("单次成功率 p = %.2f，每种 k 都重复模拟 %d 次实验。" % (p, TRIALS))
    print(pad("k", 5) + pad("Pass@k 解析", 14) + pad("Pass@k 模拟", 14) +
          pad("Pass^k 解析", 14) + pad("Pass^k 模拟", 14) + "最大误差")
    worst = 0.0
    table = []
    for k in range(1, 11):
        a, b = pass_at_k(p, k), pass_pow_k(p, k)
        sa, sb = simulate(p, k)
        err = max(abs(a - sa), abs(b - sb))
        worst = max(worst, err)
        table.append((k, a, sa, b, sb))
        print(pad(str(k), 5) + pad("%.4f" % a, 14) + pad("%.4f" % sa, 14) +
              pad("%.4f" % b, 14) + pad("%.4f" % sb, 14) + "%.4f" % err)
    print("  看这一列：p=0.9 时 Pass@10 已经接近 1.0000（十次里蒙对一次不难），")
    print("  而 Pass^10 只有 %.4f（要连对十次，业务上十次里会失败约 %.0f%%）。"
          % (pass_pow_k(p, 10), (1 - pass_pow_k(p, 10)) * 100))
    print("  结论：同一个模型，能力上限和业务可靠性是两件完全不同的事。")
    assert worst < 0.01, "蒙特卡洛与解析公式的误差必须在 1 个百分点以内"
    return table


# ------------------------------------------------------------------ 2 ASCII 图
def chart(ks, series, height=11):
    """ASCII 折线图：纵轴 0~1 共 height 格，横轴是 k。两线重合处画 *。"""
    print("     " + "".join(pad("k=%d" % k, 6) for k in ks))
    for level in range(height - 1, -1, -1):
        y = level / (height - 1)
        cells = []
        for i in range(len(ks)):
            marks = [lab for lab, vals in series if round(vals[i] * (height - 1)) == level]
            cells.append("*" if len(marks) > 1 else (marks[0] if marks else "."))
        print("%.1f |" % y + "     ".join(cells))


def section2():
    print("\n【实验 2】p=0.9 时两条曲线怎么分道扬镳（A = Pass@k，P = Pass^k）")
    ks = list(range(1, 11))
    pa = [pass_at_k(0.9, k) for k in ks]
    pp = [pass_pow_k(0.9, k) for k in ks]
    chart(ks, [("A", pa), ("P", pp)])
    print("  k=1 时两线重合（都是 0.90）—— 只跑一次的时候，「至少对一次」和「每次都对」")
    print("  是同一件事。k 一变大就分开了：A 冲向 1，P 掉到 %.2f。" % pp[-1])
    print("  → 用 Pass@k 汇报成绩会显得模型很强；但线上是 Pass^k 那种「每次都得成」。")
    return pa, pp


# ------------------------------------------------------------- 3 置信区间
def wilson(succ, n, z=1.96):
    """Wilson 区间：返回 (中心, 下界, 上界)。小样本比 p̂±z·SE 可靠得多。"""
    p = succ / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return center, max(0.0, center - half), min(1.0, center + half)


def two_prop_z(s1, n1, s2, n2):
    """两比例 z 检验：|z| > 1.96 才算在 95% 水平上显著。"""
    p1, p2 = s1 / n1, s2 / n2
    pc = (s1 + s2) / (n1 + n2)              # 合并比例（原假设下两组同分布）
    se = np.sqrt(pc * (1 - pc) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se


def required_n(d, p=0.9, z_a=1.96, z_b=0.84):
    """要把 d 这么大的差距测出显著性，每组需要多少题（95% 置信 + 80% 检验力）。"""
    return int(np.ceil((z_a + z_b) ** 2 * 2 * p * (1 - p) / d ** 2))


def section3():
    print("\n【实验 3】Wilson 95% 置信区间：benchmark 差 2% 可能毫无统计显著性")
    for n, s1, s2 in [(100, 90, 88), (10000, 9000, 8800)]:
        c1, l1, h1 = wilson(s1, n)
        c2, l2, h2 = wilson(s2, n)
        z = two_prop_z(s1, n, s2, n)
        print("\n每组 %d 题，模型 A 对了 %d 题（%.1f%%），模型 B 对了 %d 题（%.1f%%），差 2 个百分点："
              % (n, s1, 100 * s1 / n, s2, 100 * s2 / n))
        print("  A 的 95%% CI = [%.4f, %.4f]，B 的 95%% CI = [%.4f, %.4f]%s"
              % (l1, h1, l2, h2, "，区间重叠" if l1 < h2 and l2 < h1 else "，区间不重叠"))
        print("  两比例 z 检验：z = %+.2f，|z| %s 1.96 → 差异%s"
              % (z, ">" if abs(z) > 1.96 else "<", "显著 ✓" if abs(z) > 1.96 else "不显著 ✗"))
        if n == 100:
            assert abs(z) < 1.96, "每组 100 题时 2 个百分点的差距不应显著"
        else:
            assert abs(z) > 1.96, "每组 10000 题时 2 个百分点的差距应该显著"
    print("\n  要在这个水平上把 2 个百分点的差距测成显著，每组大约需要 %d 道题。" % required_n(0.02))
    print("  评测集远小于这个数时，「A 比 B 高 2%」很可能只是抽样噪声 —— 排名会随题目集改变。")


# --------------------------------------------------- 4 LLM-as-a-Judge 的偏差
def judge(a, b, rng, pos_bias=0.0, len_bias=0.0):
    """模拟裁判：a、b 都是 (质量分, 答案长度)。返回 'A' 表示判 A 更好。

    pos_bias 表示「坐在第一个位置」的额外好感，len_bias 表示每多一个字的好感。
    真实裁判没有这么直白，但偏差的方向和量级就是这么估出来的。
    """
    sa = a[0] + pos_bias + len_bias * a[1] + rng.normal(0, 0.6)
    sb = b[0] + len_bias * b[1] + rng.normal(0, 0.6)
    return "A" if sa > sb else "B"


def section4(n=3000):
    print("\n【实验 4】LLM-as-a-Judge 的两种偏差：位置偏差与长度偏差")
    rng = np.random.default_rng(SEED)
    first = second = flips = 0
    for _ in range(n):
        a, b = (1.0, 0), (1.0, 0)                      # 两份答案质量完全相同
        v_fwd = judge(a, b, rng, pos_bias=0.35)         # A 坐在第一个位置
        v_bwd = judge(b, a, rng, pos_bias=0.35)         # 交换位置：B 坐在第一个位置
        first += v_fwd == "A"                           # 原顺序下判 A 更好
        second += v_bwd == "B"                          # 交换后仍然判 A 更好
        flips += (v_fwd == "A") != (v_bwd == "B")
    r1, r2 = first / n, second / n
    print("\n① 位置偏差（%d 对答案，两份质量完全相同）：" % n)
    print("  只测一个顺序：A 胜率 %.1f%% —— 看起来「坐在第一位」就赢。" % (100 * r1))
    print("  交换位置再测：A 胜率 %.1f%% —— 同一对答案，换个顺序结论就翻了。" % (100 * r2))
    print("  配对比较 + 交换位置取平均：%.1f%% —— 偏差被抵消，逼近 50%%（本来就没差别）。"
          % (100 * (r1 + r2) / 2))
    print("  翻转比例 %.1f%% 就是位置偏差的直接指纹：同一对答案、两个顺序、两个结论。"
          % (100 * flips / n))
    debiased = (r1 + r2) / 2
    assert r1 > 0.55 and r2 < 0.45, "位置偏差应该能被观察到（且交换位置后方向翻转）"
    assert 0.48 <= debiased <= 0.52, "交换位置取平均后应该接近 50%"
    assert flips / n > 0.35, "翻转比例应该明显偏高"

    short_wins = ctrl_wins = 0
    for _ in range(n):
        short_wins += judge((1.0, 200), (1.0, 500), rng, len_bias=0.0012) == "A"
        ctrl_wins += judge((1.0, 0), (1.0, 0), rng, len_bias=0.0012) == "A"   # 长度归一化/控制
    print("\n② 长度偏差（%d 对答案，质量相同，短答案 200 字 vs 长答案 500 字）：" % n)
    print("  长答案胜率：不做控制时 %.1f%%；把长度控制住（等长截断）后 %.1f%%。"
          % (100 * (1 - short_wins / n), 100 * (1 - ctrl_wins / n)))
    print("  说明「更长=更好」是裁判的口味，不是答案的质量；配对比较 + 长度控制才能去掉它。")
    assert (1 - short_wins / n) > 0.55 and 0.48 <= 1 - ctrl_wins / n <= 0.52


def main():
    print("=" * 86)
    print("lab6 Agent 评估：Pass@k / Pass^k、Wilson 置信区间、LLM-as-a-Judge 的偏差")
    print("全部结果都由标准库 + numpy 现算，零网络、零 API、零第三方依赖。")
    print("=" * 86)
    section1()
    section2()
    section3()
    section4()
    print("\n" + "=" * 86)
    print("结论：① 报告能力用 Pass@k，承诺业务用 Pass^k，两者随 k 的走向完全相反；")
    print("      ② 任何「A 比 B 好 x%」的说法，都要先看置信区间和样本量；")
    print("      ③ 用 LLM 当裁判时，配对比较 + 交换位置 + 控制长度是最省钱的三道保险。")
    print("      思考题：① p=0.9、k=10 时 Pass^10 约等于多少？你觉得线上能接受吗？")
    print("      ② 如果两个模型的 Wilson 区间重叠，你还能说其中一个更好吗？")
    print("      ③ 位置偏差和长度偏差，还有哪些偏差是「交换位置」治不了的？")
    print("=" * 86)
    print("断言全部通过 ✓：模拟值落在解析公式 1 个百分点内；100 题的 2% 差距不显著、")
    print("                10000 题显著；位置偏差与长度偏差都能被配对比较检测并抵消。")


if __name__ == "__main__":
    main()
