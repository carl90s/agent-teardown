"""
lab5_bm25.py —— 从零实现 BM25，以及为什么生产 RAG 要用混合检索
================================================================================
对应《深入理解 AI Agent》3.2.2 稠密嵌入（p88）、3.2.3 稀疏嵌入：精确匹配的关键词
检索（p90）、3.2.4 混合检索（p93）。四种检索器，只用标准库 + numpy：
  1 BM25：关键词检索的经典算法（主角，从零实现，不使用 rank_bm25）
      score(q,d) = Σ_t IDF(t)·f(t,d)·(k1+1) / ( f(t,d) + k1·(1-b+b·|d|/avgdl) )
      IDF(t) = ln(1 + (N-df(t)+0.5)/(df(t)+0.5))；k1 控制词频饱和，b 控制长度惩罚
  2 稠密替身 A：字符 bigram 的 TF-IDF 余弦 —— 只会比字面，实验 3 展示它的死穴
  3 稠密替身 B：手工概念向量（CONCEPTS 把同义说法投影到同一条语义轴上）
      ⚠ 两个替身都不是真语义模型，真实场景请换成 bge / text-embedding-3 等嵌入模型
  4 混合检索：两路分数归一化后加权融合，或只用排名做 RRF
分词：中文按「相邻两字」切 bigram 当词，英文/数字整词小写。零依赖、零模型、零网络。
运行：python lab5_bm25.py
================================================================================
"""

import re
import sys

import numpy as np

from mockllm import pad

if not sys.stdout.isatty():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

TITLES = ["ReAct 循环", "KV Cache 与前缀缓存", "RAG 检索增强生成", "MCP 工具协议",
          "上下文压缩", "Agent 记忆与状态栏", "多 Agent 协作", "BM25 关键词检索", "工具调用"]
DOCS = [
    "ReAct 让模型把思考和行动交错起来：先推理下一步做什么，再调用工具，最后根据观察修正推理。",
    "KV Cache 保存每层算过的键值向量。请求前缀逐字节不变时就能复用，不必重复计算，命中率越高账单越低。",
    "RAG 先检索再生成：把文档切片建索引，用查询召回片段，再让模型基于片段作答并给出引用来源。",
    "MCP 是一套标准协议：客户端把工具列表暴露给模型，服务端真正执行，模型不必知道工具内部怎么实现。",
    "上下文压缩：长会话的轨迹不断膨胀，把旧消息换成摘要，或把子任务隔离到独立上下文，能避免装不下窗口。",
    "Agent 的记忆要跨轮次保存进度：用状态栏记录待办列表、已完成步骤和关键结论，进程重启后还能接着做。",
    "多 Agent 协作：主 Agent 把任务拆解成子任务，子 Agent 各自执行，只把结论回传给主线，避免互相干扰。",
    "BM25 用词频和逆文档频率给文档打分，再做文档长度归一化：k1 控制词频饱和，b 控制长度惩罚。",
    "工具调用要写好函数签名和参数说明：参数校验失败时把错误信息回传给模型，让它修正参数后重试。",
]

# --------------------------------------------------------------- 分词与公共底座
def tokenize(text):
    """中文按相邻两字切成 bigram 当词；英文/数字整词小写。返回 token 列表。"""
    tokens = []
    for chunk in re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", text):
        if chunk[0].isascii():
            tokens.append(chunk.lower())
        else:
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return tokens

def build_tf(docs):
    """公共底座：分词 → 词表 → 词频矩阵 tf → IDF → 文档长度 dl。"""
    tokens = [tokenize(d) for d in docs]
    vocab = {}
    for ts in tokens:
        for t in ts:
            vocab.setdefault(t, len(vocab))              # 词 -> 列号，按出现顺序编号
    tf = np.zeros((len(docs), len(vocab)))
    for i, ts in enumerate(tokens):
        for t in ts:
            tf[i, vocab[t]] += 1                         # 累加词频 f(t,d)
    df = (tf > 0).sum(axis=0)                            # 文档频率：含这个词的文档数
    idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
    dl = np.array([len(ts) for ts in tokens], dtype=float)
    return vocab, tf, idf, dl

# ------------------------------------------------------------------ 1 BM25
class BM25:
    """从零实现的 BM25：只用词频、逆文档频率和文档长度归一化，没有任何模型。"""

    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.vocab, self.tf, self.idf, self.dl = build_tf(docs)
        self.N = len(docs)
        self.avgdl = float(self.dl.mean())

    def scores(self, query):
        """返回每篇文档的 BM25 分数：k1/b 只在打分时起作用。"""
        idx = [self.vocab[t] for t in tokenize(query) if t in self.vocab]
        if not idx:
            return np.zeros(self.N)                      # 一个词都没命中，全部吃零分
        f = self.tf[:, idx]                              # 词频 f(t,d)
        norm = 1 - self.b + self.b * self.dl / self.avgdl           # 长度归一化因子
        sat = f * (self.k1 + 1) / (f + self.k1 * norm[:, None])     # 词频饱和
        return (sat * self.idf[idx]).sum(axis=1)

    def search(self, query, top_k=3):
        """对外检索接口：返回前 top_k 名的文档下标（第 0 位就是第一名）。"""
        return list(np.argsort(-self.scores(query)))[:top_k]

# ------------------------------------------- 2 稠密替身 A：字符 bigram 的 TF-IDF
class CharBigramTfidf:
    """稠密替身 A：字符 bigram 的 TF-IDF + 余弦。⚠ 只有字面重叠能力，换同义词就失效。"""

    def __init__(self, docs):
        self.vocab, self.tf, self.idf, self.dl = build_tf(docs)
        mat = self.tf * self.idf                                    # TF-IDF 矩阵
        n = np.linalg.norm(mat, axis=1)
        self.mat = mat / np.where(n == 0, 1, n)[:, None]            # 逐行归一化，便于算余弦

    def scores(self, query):
        vec = np.zeros(len(self.vocab))
        for t in tokenize(query):
            if t in self.vocab:
                vec[self.vocab[t]] += 1
        n = np.linalg.norm(vec)
        return self.mat @ (vec / (n if n else 1))                   # 点积 = 余弦相似度

# ------------------------------------------- 3 稠密替身 B：手工概念向量（语义轴）
CONCEPTS = [
    ("ReAct 循环", ["react", "推理", "思考", "行动", "观察", "交错", "循环"]),
    ("KV Cache", ["cache", "缓存", "前缀", "命中", "复用", "重复计算", "省钱", "账单"]),
    ("RAG 检索", ["rag", "检索", "索引", "召回", "引用", "向量", "嵌入", "相似"]),
    ("MCP 协议", ["mcp", "协议", "客户端", "服务端", "工具列表", "标准"]),
    ("上下文压缩", ["压缩", "摘要", "上下文", "窗口", "长会话", "膨胀", "装不下"]),
    ("记忆与状态", ["记忆", "状态栏", "待办", "进度", "重启", "跨轮次"]),
    ("多 Agent 协作", ["智能体", "agent", "协作", "协同", "配合", "分工", "拆解", "子任务", "打架", "干扰"]),
    ("BM25 检索", ["bm25", "关键词", "词频", "逆文档频率", "长度归一化", "长度惩罚", "精确匹配"]),
    ("工具调用", ["工具调用", "函数签名", "参数", "校验", "重试", "错误信息"]),
]

class ConceptVectors:
    """稠密替身 B：手工词表把「同义说法」投影到同一条概念轴上。
    ⚠ 真实场景用嵌入模型编码整句话；这张表只是为了让离线实验能演示语义检索。"""

    def __init__(self, docs):
        self.terms = [[w.lower() for w in c[1]] for c in CONCEPTS]
        self.mat = self._encode(docs)

    def _encode(self, texts):
        mat = np.zeros((len(texts), len(CONCEPTS)))
        for i, text in enumerate(texts):
            low = text.lower()
            for j, words in enumerate(self.terms):
                mat[i, j] = sum(1 for w in words if w in low)   # 命中了几个同义说法
        n = np.linalg.norm(mat, axis=1)
        return mat / np.where(n == 0, 1, n)[:, None]

    def scores(self, query):
        return self.mat @ self._encode([query])[0]

# ------------------------------------------------------------------ 4 混合检索
def normalize(s):
    """把一路分数线性压到 [0,1]，不同检索器的分数才有可比性。"""
    lo, hi = float(np.min(s)), float(np.max(s))
    return (s - lo) / (hi - lo) if hi > lo else np.zeros_like(s)

def rrf(rankings, k=60):
    """Reciprocal Rank Fusion：只用排名、不用分数，跨检索器天然可比。"""
    out = np.zeros(len(rankings[0]))
    for order in rankings:
        for pos, doc in enumerate(order):
            out[doc] += 1.0 / (k + pos + 1)
    return out

def show(title, scores, top=4):
    """打印前 top 名，返回完整名次（第 0 位就是第一名）。"""
    print(title)
    order = list(np.argsort(-scores))
    for pos, i in enumerate(order[:top], 1):
        print(pad("  第 %d 名" % pos, 12) + pad(TITLES[i], 22) + "得分 %.4f" % scores[i])
    return order

def main():
    bm25, bitfidf, concept = BM25(DOCS), CharBigramTfidf(DOCS), ConceptVectors(DOCS)
    print("=" * 86)
    print("lab5 从零实现 BM25 + 两种稠密检索替身 + 混合检索（%d 篇中文短文档）" % len(DOCS))
    print("BM25：k1=%.1f（词频饱和），b=%.2f（长度惩罚），平均文档长度 %.1f 个 token；" % (bm25.k1, bm25.b, bm25.avgdl))
    print("分词 = 中文相邻两字 bigram + 英文整词小写。零依赖、零模型、零网络。")
    print("=" * 86)

    # ---------------- 实验 1：关键词查询，BM25 的主场 ----------------
    q1 = "BM25 用词频和逆文档频率打分，长度归一化靠什么参数控制"
    print("\n【实验 1】关键词查询（BM25 的主场，assert 检查排名）\n查询：%s" % q1)
    o1 = show("BM25 排名：", bm25.scores(q1))
    assert o1[0] == 7, "关键词查询的第一名应该是《BM25 关键词检索》"
    print("  → 这些词几乎只在这一篇里出现：命中集中 + IDF 高，所以它稳稳排第一。")
    print("  BM25.search(q1, 3) 返回前 3 名：" + "、".join(TITLES[i] for i in bm25.search(q1)))

    # ---------------- 实验 2：k1 / b 怎么影响排名 ----------------
    print("\n【实验 2】调 k1 和 b：分数怎么变（同一查询，只改参数）")
    q2 = "长度归一化 长度惩罚 文档长度"
    print("查询：%s" % q2)
    print(pad("参数设置", 32) + pad("排第一的文档", 24) + "《BM25 关键词检索》得分")
    for label, k1, b in [("k1=1.5, b=0.75（默认）", 1.5, 0.75),
                         ("k1=1.5, b=0.0（不惩罚长文）", 1.5, 0.0),
                         ("k1=5.0, b=0.75（词频几乎不饱和）", 5.0, 0.75),
                         ("k1=1.5, b=1.0（长度惩罚拉满）", 1.5, 1.0)]:
        s = BM25(DOCS, k1=k1, b=b).scores(q2)
        print(pad(label, 32) + pad(TITLES[int(np.argmax(s))], 24) + "%.4f" % s[7])
        assert int(np.argmax(s)) == 7 and s[7] > 0, "换 k1/b 后目标文档仍应排第一"
    print("  观察：k1 越大，重复出现的词越占便宜；b 越大，长文档越吃亏。")

    # ---------------- 实验 3：替身 A 能做和不能做的事 ----------------
    print("\n【实验 3】稠密替身 A（字符 bigram TF-IDF 余弦）能做和不能做的事")
    q3 = "怎么复用已经算过的结果，避免重复计算还省钱"
    print("查询：%s" % q3)
    o3 = show("替身 A 排名：", bitfidf.scores(q3))
    assert o3[0] == 1, "这个查询和《KV Cache 与前缀缓存》字面重叠最多"
    print("  → 措辞相近时它排对了：字面重叠就是它的全部本事。")
    q4 = "智能体怎么协同工作"
    print("\n换个说法再问一次（同义词，一个两字组合都不重合）：%s" % q4)
    o4 = show("替身 A 排名：", bitfidf.scores(q4))
    print("  → 目标本该是《多 Agent 协作》，但语料写的是「Agent / 协作 / 互相干扰」：\n    一个两字组合都不重合，所以它吃零分。死穴：**只会比字面，不会比意思。**")
    assert o4[0] != 6, "字符 bigram 替身在这里必然失败，这正是要演示的局限"

    # ---------------- 实验 4：BM25 失败、混合检索成功 ----------------
    print("\n【实验 4】构造一个「BM25 失败、混合检索成功」的查询")
    q5 = "一群智能体如何分工配合，怎样让彼此不打架"
    print("查询：%s" % q5)
    print("期望答案：《多 Agent 协作》—— 语料里它叫「主 Agent / 子 Agent / 拆解 / 干扰」。")
    sb = bm25.scores(q5)
    ob = show("BM25 排名：", sb)
    print("  → BM25 最高分只有 %.4f：查询词一个都没出现在语料里，关键词检索直接失明。" % float(sb.max()))
    sc = concept.scores(q5)
    oc = show("替身 B（概念向量，即嵌入模型的替身）排名：", sc)
    print("  → 词表把「智能体 / 分工 / 配合 / 打架」和「Agent / 拆解 / 干扰」映射到同一条\n    语义轴，所以它不看字面也能把这句大白话对到《多 Agent 协作》。")
    fused = 0.5 * normalize(sb) + 0.5 * normalize(sc) + 1e-9 * normalize(sc)
    of = show("混合检索（两路分数归一化后 0.5:0.5 融合）排名：", fused)
    naive = int(np.argmax(rrf([ob, oc])))
    print(pad("RRF 直接融合两路排名 → 第一：", 34) + TITLES[naive])
    print("  注意它排错了：BM25 全体零分时 np.argsort 退化成 [0,1,...,8] 这个任意顺序，")
    print("  RRF 就把「随机名次」当成了信号。所以融合前要先判断每一路是否真有命中。")
    routes = [o for o, s in [(ob, sb), (oc, sc)] if float(s.max()) > 0]
    rrf_top = int(np.argmax(rrf(routes)))
    print(pad("只融合有信号的那一路 → 第一：", 34) + TITLES[rrf_top])
    assert int(ob[0]) != 6 and float(sb.max()) == 0.0, "BM25 必须在这里失明，例子才成立"
    assert int(oc[0]) == 6 and int(of[0]) == 6 and rrf_top == 6, "混合检索应修回《多 Agent 协作》"
    print("""
  为什么混合检索能修好？因为两路信号的失败模式恰好互补 ——
    BM25 便宜、可解释、对专有名词和错误码极其可靠，但用户换一种说法就召回不到；
    稠密检索能跨措辞匹配，但需要模型和算力，还可能把「字面很像、意思不同」的排前面。
  生产 RAG 的常见结构：混合检索负责召回（宁可多拿一份），重排序模型负责收敛。""")

    print("=" * 86)
    print("结论：BM25 是「精确匹配」的专家，稠密检索是「意思相近」的专家；")
    print("      检索质量的上限取决于语料，召回率的上限取决于你用了几路信号。")
    print("      思考题：① k1 调大、b 调小分别会让哪类查询变好？② 中文改按单字切分，")
    print("      BM25 排名会怎么变？③ 0.5:0.5 这个融合权重，你会用什么办法定下来？")
    print("=" * 86)

    assert int(np.argmax(bm25.scores(q1))) == 7 and o1[1] != 7, "BM25 对关键词查询应排对"
    print("断言全部通过 ✓：关键词查询 BM25 排第一；替身 A 换措辞时如实失败；")
    print("                混合检索把 BM25 排错的查询修回《%s》" % TITLES[int(of[0])])

if __name__ == "__main__":
    main()
