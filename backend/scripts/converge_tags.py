"""标签词表收敛分析（只读，不动任何数据）。

按 plan 里的收敛一期方案：embedding 余弦聚类找「候选合并簇」+ 单例标签清单，
输出人类可读报告（eval/tag_convergence_report.txt），供人工审阅后决定合并映射。
本次不改 tag_words / articles / Milvus 的任何数据。

运行：backend/.venv/Scripts/python.exe scripts/converge_tags.py
"""

from collections import defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.tag_word import TagWord

THRESHOLD = 0.75          # 余弦 ≥ 此值视为候选近义
SINGLETON_MAX_DOCS = 1    # 覆盖文章数 ≤ 此值视为孤儿标签
OUT = Path(__file__).resolve().parent.parent.parent / "eval" / "tag_convergence_report.txt"


def cosine_matrix(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return (vecs / norms) @ (vecs / norms).T


def main() -> None:
    with SessionLocal() as db:
        words = db.execute(select(TagWord.word, TagWord.embedding)).all()
        # 每个标签在 articles 中的覆盖数（jsonb 展开计数）
        usage = dict(
            db.execute(
                text(
                    "SELECT tag, COUNT(*) FROM articles, "
                    "jsonb_array_elements_text(tags) AS tag "
                    "WHERE deleted_at IS NULL GROUP BY tag"
                )
            ).all()
        )

    wlist = [w for w, _ in words]
    embs = np.array([e for _, e in words], dtype=np.float32)
    print(f"词表 {len(wlist)} 个，全部带 embedding，开始聚类分析...")

    sim = cosine_matrix(embs)

    # 并查集聚类：相似 ≥ 阈值的词合并成簇
    parent = list(range(len(wlist)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = []
    for i in range(len(wlist)):
        for j in range(i + 1, len(wlist)):
            if sim[i][j] >= THRESHOLD:
                pairs.append((wlist[i], wlist[j], float(sim[i][j])))
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(wlist)):
        clusters[find(i)].append(i)
    merged = {r: idxs for r, idxs in clusters.items() if len(idxs) > 1}

    # 单例标签（覆盖文章数过少的孤儿）
    singletons = sorted(
        ((w, usage.get(w, 0)) for w in wlist if usage.get(w, 0) <= SINGLETON_MAX_DOCS),
        key=lambda x: x[1],
    )

    lines = []
    lines.append(f"标签词表收敛分析报告  阈值={THRESHOLD}  词表={len(wlist)}")
    lines.append("=" * 70)
    lines.append(f"候选合并簇: {len(merged)} 个（涉及 {sum(len(v) for v in merged.values())} 个）")
    lines.append(f"单例/孤儿标签（覆盖≤{SINGLETON_MAX_DOCS}篇）: {len(singletons)} 个")
    lines.append("")

    lines.append("【一、候选合并簇】（保留建议 = 簇内覆盖文章最多的词）")
    for _r, idxs in sorted(merged.items(), key=lambda kv: -len(kv[1])):
        def _max_sim(i: int, _idxs: list = idxs) -> float:
            return float(max(sim[i][j] for j in _idxs if j != i)) if len(_idxs) > 1 else 0.0

        members = sorted(
            ((wlist[i], usage.get(wlist[i], 0), _max_sim(i)) for i in idxs),
            key=lambda x: -x[1],
        )
        keep = members[0][0]
        others = ", ".join(f"{w}({n}篇, 相似{sc:.2f})" for w, n, sc in members[1:])
        lines.append(f"  → 保留「{keep}」（{members[0][1]}篇） ← {others}")
    lines.append("")

    lines.append("【二、单例/孤儿标签】（候选下沉或直接删除，需逐个人工裁决）")
    for w, n in singletons:
        lines.append(f"  {w}  ({n}篇)")
    lines.append("")

    # 高频 Top20 对照
    top = sorted(((w, usage.get(w, 0)) for w in wlist), key=lambda x: -x[1])[:20]
    lines.append("【三、高频 Top20 对照】")
    for w, n in top:
        lines.append(f"  {w}  ({n}篇)")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"候选合并簇 {len(merged)} 个 | 孤儿标签 {len(singletons)} 个")
    print(f"报告已写入 {OUT}")
    # 终端预览前 30 行
    for line in lines[:30]:
        print(line)


if __name__ == "__main__":
    main()
