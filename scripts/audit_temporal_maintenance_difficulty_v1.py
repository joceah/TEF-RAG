"""DIAGNOSTIC ONLY difficulty audit for temporal_maintenance_dev_v2.

Gold/authoring metadata are read only to characterize the already-generated dev
benchmark and score frozen retrieval outputs.  Nothing produced here is a
retrieval input, and no model call, tuning, or data regeneration is performed.
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from scripts.evaluate_temporal_baselines_v2 import score
from scripts.temporal_maintenance_dataset_v2_lib import ROOT, visible


DATA = ROOT / "data/generated/temporal_maintenance_dev_v2"
RUN = ROOT / "experiments/analyses/formal_temporal_rag_v1/rankings_combined.jsonl"
OUT = ROOT / "experiments/analyses/temporal_maintenance_dev_v2_difficulty_audit"
MANIFEST_OUT = ROOT / "experiments/analyses/temporal_maintenance_dataset_v2/temporal_hard_not_recency_solvable_manifest.jsonl"
K = 5

LABEL_ORDER = [
    "RECENCY_ONLY",
    "MULTI_EPISODE_DISAMBIGUATION",
    "CUTOFF_SENSITIVE",
    "LATE_ARRIVING_EVIDENCE",
    "SUPERSEDED_DIAGNOSIS",
    "PROCEDURE_VERSIONING",
    "CROSS_SOURCE_REQUIRED",
    "SIMILAR_SYMPTOM_DIFFERENT_CAUSE",
    "PERSISTENT_UNCERTAINTY",
]

# These mappings encode the authored scenario semantics, not observed method errors.
SCENARIO_LABELS = {
    "C01": {"MULTI_EPISODE_DISAMBIGUATION", "CUTOFF_SENSITIVE"},
    "C02": {"MULTI_EPISODE_DISAMBIGUATION", "CUTOFF_SENSITIVE"},
    "C03": {"CUTOFF_SENSITIVE", "SIMILAR_SYMPTOM_DIFFERENT_CAUSE"},
    "C04": {"CUTOFF_SENSITIVE"},
    "C05": {"CUTOFF_SENSITIVE", "LATE_ARRIVING_EVIDENCE"},
    "C06": {"CUTOFF_SENSITIVE"},
    "C07": {"CUTOFF_SENSITIVE", "SIMILAR_SYMPTOM_DIFFERENT_CAUSE"},
    "C08": {"CUTOFF_SENSITIVE", "SUPERSEDED_DIAGNOSIS"},
    "C09": {"CUTOFF_SENSITIVE", "LATE_ARRIVING_EVIDENCE"},
    "C10": {"MULTI_EPISODE_DISAMBIGUATION", "CUTOFF_SENSITIVE"},
    "C11": {"CUTOFF_SENSITIVE", "PROCEDURE_VERSIONING"},
    "C12": {"CUTOFF_SENSITIVE", "PROCEDURE_VERSIONING"},
    "C13": {"CUTOFF_SENSITIVE"},
    "C14": {"CUTOFF_SENSITIVE", "SUPERSEDED_DIAGNOSIS"},
    "C15": {"CUTOFF_SENSITIVE", "SUPERSEDED_DIAGNOSIS"},
    "C16": {"CUTOFF_SENSITIVE", "SUPERSEDED_DIAGNOSIS"},
}

REASONS = {
    "RECENCY_ONLY": "all necessary evidence groups are covered by the five newest visible records for the target device",
    "MULTI_EPISODE_DISAMBIGUATION": "the authored task distinguishes recurrence, reopening, or concurrent work episodes on the same asset",
    "CUTOFF_SENSITIVE": "the paired authored query cutoffs expose different evidence states and answers",
    "LATE_ARRIVING_EVIDENCE": "the scenario explicitly separates event time from later evidence availability",
    "SUPERSEDED_DIAGNOSIS": "a later correction, review, or investigation updates an earlier account",
    "PROCEDURE_VERSIONING": "the answer depends on the procedure/model rule valid at the query time",
    "CROSS_SOURCE_REQUIRED": "necessary evidence spans multiple record kinds or assets",
    "SIMILAR_SYMPTOM_DIFFERENT_CAUSE": "the scenario contrasts similar symptoms whose supported explanation differs",
    "PERSISTENT_UNCERTAINTY": "the authored chain remains underdetermined at the later cutoff and requires uncertainty to be preserved",
}

METHODS = {
    "latest_device": "Latest",
    "bm25_visible": "BM25",
    "hybrid_device": "Hybrid",
    # This is the frozen full-coverage main method available for this dataset.
    "tmc_v2": "TMC-RAG-v2 (frozen)",
}


def lines(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def dump_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mean(rows, key):
    return sum(float(r[key]) for r in rows) / len(rows) if rows else None


def pct(n, d):
    return round(100 * n / d, 2) if d else 0.0


def group_covered(ids, groups):
    chosen = set(ids)
    return all(chosen.intersection(group) for group in groups)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    queries = {q["query_id"]: q for q in lines(DATA / "queries.jsonl")}
    gold = {g["query_id"]: g for g in lines(DATA / "evaluation/gold.jsonl")}
    chains = {c["chain_id"]: c for c in lines(DATA / "evaluation/chains.jsonl")}
    docs = {d["id"]: d for d in lines(DATA / "evidence.jsonl")}
    assets = {a["asset_id"]: a for a in json.loads((DATA / "assets.json").read_text(encoding="utf-8-sig"))}
    assert len(queries) == len(gold) == 1152

    asset_chain_count = Counter(c["asset_id"] for c in chains.values())
    audit_rows = []
    for qid, q in queries.items():
        g = gold[qid]
        c = chains[g["chain_id"]]
        required_ids = {eid for group in g["required_evidence_groups"] for eid in group}
        required_docs = [docs[eid] for eid in required_ids]
        source_kinds = sorted({d["kind"] for d in required_docs})
        source_assets = sorted({d["asset_id"] for d in required_docs})
        newest = sorted(
            (d for d in docs.values() if d["asset_id"] == q["asset_id"] and visible(d, q["query_time"])),
            key=lambda d: (d["event_time"], d["available_at"], d["id"]),
            reverse=True,
        )[:K]
        recency = group_covered([d["id"] for d in newest], g["required_evidence_groups"])
        labels = set()
        if g["task"] == "ordinary":
            labels.add("RECENCY_ONLY")
        else:
            labels.update(SCENARIO_LABELS[c["scenario"]])
            if recency:
                labels.add("RECENCY_ONLY")
            if len(source_kinds) > 1 or len(source_assets) > 1:
                labels.add("CROSS_SOURCE_REQUIRED")
            if c["persistent_unknown"]:
                labels.add("PERSISTENT_UNCERTAINTY")
        ordered = [x for x in LABEL_ORDER if x in labels]
        reasons = [f"{x}: {REASONS[x]}" for x in ordered]
        audit_rows.append({
            "query_id": qid,
            "asset": q["asset_id"],
            "task": g["task"],
            "scenario": c["scenario"],
            "theme": c["theme"],
            "prototype_query": g["prototype_query"],
            "query_time": q["query_time"],
            "query_text": q["text"],
            "difficulty_labels": "|".join(ordered),
            "reason": "; ".join(reasons),
            "source_requirements": f"kinds={','.join(source_kinds)}; assets={','.join(source_assets)}",
            "episode_count": asset_chain_count[q["asset_id"]],
            "required_group_count": len(g["required_evidence_groups"]),
            "recency_solvable_at_5": recency,
            "persistent_unknown": c["persistent_unknown"],
            "diagnostic_only": True,
        })

    fields = list(audit_rows[0])
    with (OUT / "query_difficulty.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(audit_rows)

    by_qid = {r["query_id"]: r for r in audit_rows}
    strata = [
        ("ALL", lambda r: True),
        ("TEMPORAL_HARD_NOT_RECENCY_SOLVABLE", lambda r: r["task"] == "temporal" and not r["recency_solvable_at_5"]),
    ] + [(lab, lambda r, lab=lab: lab in r["difficulty_labels"].split("|")) for lab in LABEL_ORDER]
    baseline_rows = []
    if RUN.exists():
        ranks = [r for r in lines(RUN) if r["method"] in METHODS]
        assert Counter(r["method"] for r in ranks) == Counter({m: 1152 for m in METHODS})
        metrics = []
        for r in ranks:
            q, g = queries[r["query_id"]], gold[r["query_id"]]
            c = chains[g["chain_id"]]
            metrics.append({"query_id": r["query_id"], "method": r["method"],
                            **score(r["evidence_ids"], q, g, docs, c, assets, K)})
        for label, predicate in strata:
            qids = {r["query_id"] for r in audit_rows if predicate(r)}
            for method, display in METHODS.items():
                subset = [r for r in metrics if r["method"] == method and r["query_id"] in qids]
                baseline_rows.append({
                    "difficulty": label, "n": len(qids), "method": display,
                    "recall_at_5": mean(subset, "recall"), "ndcg_at_5": mean(subset, "ndcg"),
                    "complete_at_5": mean(subset, "complete"),
                })
        mmap = {(r["query_id"], r["method"]): r for r in metrics}
        wtl = []
        for label, predicate in strata:
            qids = [r["query_id"] for r in audit_rows if predicate(r)]
            for metric in ("recall", "ndcg", "complete"):
                counts_wtl = Counter()
                for qid in qids:
                    delta = mmap[qid, "tmc_v2"][metric] - mmap[qid, "latest_device"][metric]
                    counts_wtl["win" if delta > 1e-12 else "loss" if delta < -1e-12 else "tie"] += 1
                wtl.append({"difficulty": label, "metric": f"{metric}@5", "n": len(qids), **counts_wtl})
        with (OUT / "tmc_rag_v2_vs_latest_wtl.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["difficulty", "metric", "n", "win", "tie", "loss"], restval=0)
            w.writeheader(); w.writerows(wtl)
    else:
        # The compact GitHub package omits the bulky frozen rankings. Reuse the
        # already archived aggregate values and regenerate labels/report only.
        with (OUT / "baseline_by_difficulty.csv").open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                row["method"] = "TMC-RAG-v2 (frozen)" if row["method"].startswith("TEF") else row["method"]
                row["n"] = int(row["n"])
                for key in ("recall_at_5", "ndcg_at_5", "complete_at_5"):
                    row[key] = float(row[key])
                baseline_rows.append(row)
    with (OUT / "baseline_by_difficulty.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(baseline_rows[0])); w.writeheader(); w.writerows(baseline_rows)

    counts = {lab: sum(lab in r["difficulty_labels"].split("|") for r in audit_rows) for lab in LABEL_ORDER}
    task_dist = {}
    for task in ("ordinary", "temporal"):
        subset = [r for r in audit_rows if r["task"] == task]
        task_dist[task] = {lab: {"count": sum(lab in r["difficulty_labels"].split("|") for r in subset),
                                 "percent": pct(sum(lab in r["difficulty_labels"].split("|") for r in subset), len(subset))}
                           for lab in LABEL_ORDER}
    hard_labels = set(LABEL_ORDER) - {"RECENCY_ONLY"}
    temporal = [r for r in audit_rows if r["task"] == "temporal"]
    hard_temporal = [r for r in temporal if hard_labels.intersection(r["difficulty_labels"].split("|"))]
    operational_hard = [r for r in hard_temporal if not r["recency_solvable_at_5"]]
    if len(operational_hard) != 196:
        raise RuntimeError(f"hard development manifest must contain 196 queries, got {len(operational_hard)}")
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for row in sorted(operational_hard, key=lambda item: item["query_id"]):
            g = gold[row["query_id"]]
            c = chains[g["chain_id"]]
            manifest_row = {
                "query_id": row["query_id"],
                "intent_id": g.get("intent_id"),
                "asset_id": row["asset"],
                "chain_id": g["chain_id"],
                "task": row["task"],
                "scenario": row["scenario"],
                "theme": row["theme"],
                "difficulty_labels": row["difficulty_labels"].split("|"),
                "query_time": row["query_time"],
                "cutoff": g.get("cutoff") or row["query_time"],
                "required_evidence_groups": g["required_evidence_groups"],
                "recency_solvable_at_5": False,
                "diagnostic_status": "seen development diagnostic subset",
                "independent_validation_or_test": False,
            }
            handle.write(json.dumps(manifest_row, ensure_ascii=False, sort_keys=True) + "\n")
    co = Counter()
    for r in audit_rows:
        labs = r["difficulty_labels"].split("|")
        for i, a in enumerate(labs):
            for b in labs[i + 1:]: co[f"{a}|{b}"] += 1
    summary = {
        "dataset": "temporal_maintenance_dev_v2", "audit_scope": "DIAGNOSTIC ONLY",
        "queries": len(audit_rows), "intents": len({g["intent_id"] for g in gold.values()}),
        "label_distribution": {lab: {"count": counts[lab], "percent": pct(counts[lab], len(audit_rows))} for lab in LABEL_ORDER},
        "average_labels_per_query": sum(len(r["difficulty_labels"].split("|")) for r in audit_rows) / len(audit_rows),
        "recency_solvable_at_5": {"count": sum(r["recency_solvable_at_5"] for r in audit_rows),
                                  "percent": pct(sum(r["recency_solvable_at_5"] for r in audit_rows), len(audit_rows))},
        "temporal_recency_solvable_at_5": {"count": sum(r["recency_solvable_at_5"] for r in temporal),
                                           "percent": pct(sum(r["recency_solvable_at_5"] for r in temporal), len(temporal))},
        "temporal_hard_any": {"count": len(hard_temporal), "percent": pct(len(hard_temporal), len(temporal)),
                              "definition": "temporal query with at least one non-RECENCY_ONLY label"},
        "temporal_hard_not_recency_solvable": {"count": len(operational_hard), "percent": pct(len(operational_hard), len(temporal)),
                                                "definition": "temporal query with a structural temporal label whose necessary evidence is not covered by Latest-5"},
        "task_distribution": task_dist,
        "cooccurrence": dict(co.most_common()),
        "method_mapping": METHODS,
        "notes": [
            "Gold, authoring chains, and relevance judgments were used only for offline audit/evaluation.",
            "RECENCY_ONLY and recency_solvable_at_5 may coexist with temporal labels; the former denotes structural coverage by newest records, not absence of temporal wording.",
            "The dataset's full-coverage frozen main-method run is named tmc_v2 and is reported unambiguously as TMC-RAG-v2 (frozen), not TEF-RAG-v5.",
            "The 196-query hard manifest is a seen development diagnostic subset, NOT independent validation/test.",
            "Counts include two deterministic phrasings per intent; there are 576 intents, so query rows are not independent samples.",
        ],
    }
    dump_json(OUT / "difficulty_summary.json", summary)

    bmap = {(r["difficulty"], r["method"]): r for r in baseline_rows}
    def fmt(x): return f"{x:.4f}" if x is not None else "NA"
    matrix = ["| Difficulty | N | Latest R/nDCG/C | BM25 R/nDCG/C | Hybrid R/nDCG/C | TMC-RAG-v2 (frozen) R/nDCG/C |",
              "|---|---:|---:|---:|---:|---:|"]
    for label, _ in strata:
        row = bmap[label, "Latest"]
        vals = []
        for method in METHODS.values():
            x = bmap[label, method]; vals.append("/".join(fmt(x[k]) for k in ("recall_at_5", "ndcg_at_5", "complete_at_5")))
        matrix.append(f"| {label} | {row['n']} | " + " | ".join(vals) + " |")

    examples = []
    for label in LABEL_ORDER[1:]:
        candidates = [r for r in audit_rows if label in r["difficulty_labels"].split("|")]
        if candidates:
            r = sorted(candidates, key=lambda x: x["query_id"])[0]
            examples.append(f"- **{label}** — `{r['query_id']}` ({r['scenario']} {r['theme']}): {r['reason']}")

    report = f"""# temporal_maintenance_dev_v2 Difficulty Audit

> **DIAGNOSTIC ONLY.** 本审计读取 authoring chain、gold evidence 与 evaluation metadata 仅用于离线难度刻画和冻结结果评测；这些字段不得进入 retrieval。未修改算法、权重或数据，未调用 LLM。数据为 dev，不是独立 test；未混入 v5 16-query stress set。

## Dataset overview

- 1152 query / 576 intent（每个 intent 两种确定性表达），192 条合成链，48 台目标设备。
- ordinary 384，temporal 768。扩展记录没有逐条专家审核，query 不能视为 1152 个独立真实事件。
- 本审计复用冻结 `rankings_combined.jsonl` 与仓库既有 `score()`，Top-k 固定为 5。

## Difficulty taxonomy and deterministic rules

结构标签来自 authored scenario、双 cutoff、必要证据组的 record kind / asset、规程场景和 persistent_unknown 标记。`RECENCY_ONLY` 采用可审计的结构判据：同设备、双时间可见、按 `(event_time, available_at)` 倒序的前 5 条覆盖全部必要证据组。它可以与其他标签共存，表示题目虽有时序措辞，但 Latest-5 已足够，并非由某算法失败反推。

## Difficulty distribution

| Difficulty | Count | Percent |
|---|---:|---:|
""" + "\n".join(f"| {lab} | {counts[lab]} | {pct(counts[lab], len(audit_rows)):.2f}% |" for lab in LABEL_ORDER) + f"""

平均每 query {summary['average_labels_per_query']:.3f} 个标签。普通/temporal 的完整分布见 `difficulty_summary.json`。

## Recency-solvable analysis

全部 query 中 Latest-5 结构可解 {summary['recency_solvable_at_5']['count']}/{len(audit_rows)}（{summary['recency_solvable_at_5']['percent']:.2f}%）；768 个 temporal query 中为 {summary['temporal_recency_solvable_at_5']['count']}/768（{summary['temporal_recency_solvable_at_5']['percent']:.2f}%）。这直接衡量“same device + newest records”是否覆盖 gold，而不是把 Latest 的最终均值当作难度定义。

## Baseline capability matrix (Recall@5 / nDCG@5 / Complete@5)

""" + "\n".join(matrix) + """

**方法命名说明：** 全 1152 题的冻结主方法结果 `tmc_v2` 明确标为 `TMC-RAG-v2 (frozen)`；它不是 TEF-RAG-v5。仓库没有覆盖该数据集全部题目的 TEF-RAG-v5 运行，因此不伪造或混入 16 题 stress set。逐 difficulty 数值见 `baseline_by_difficulty.csv`，逐层 TMC-RAG-v2-vs-Latest 的 Recall/nDCG/Complete 胜平负见 `tmc_rag_v2_vs_latest_wtl.csv`。

## Important examples

""" + "\n".join(examples) + """

## Main findings and dataset gaps

""" + f"""768 个 temporal query 中，572 个（74.48%）的必要证据已被 Latest-5 结构覆盖；只有 {len(operational_hard)} 个（{pct(len(operational_hard), len(temporal)):.2f}%）同时具有时序结构标签且 Latest-5 不能覆盖。该 196-query 清单是 **seen development diagnostic subset，NOT independent validation/test**。总体均值因此主要测到设备过滤与倒序覆盖。更关键的是，TMC-RAG-v2 (frozen) 在 `PROCEDURE_VERSIONING/CROSS_SOURCE_REQUIRED` 的 Recall@5 为 0.6250，低于 Latest 的 0.6354，Complete@5 均为 0；在 `LATE_ARRIVING_EVIDENCE` 也低于 Latest（0.9818 vs 0.9948）。它只在 `MULTI_EPISODE`（0.9132 vs 0.8808）和 `SIMILAR_SYMPTOM_DIFFERENT_CAUSE`（0.9479 vs 0.8976）显示较清楚的 Recall 优势。因此数据偏易与算法未稳定利用 hard structure 两者同时存在。

当前设计的主要缺口是：difficulty 由 16 个原型模板参数化复制，类别与 scenario 高度绑定；两个改写共享 intent/gold；缺少更多相互独立的 cutoff 对、跨链交织的长历史、自然形成的多源缺失组合，以及真实规程修订/撤回链。`CUTOFF_SENSITIVE` 覆盖广但不等于 cutoff 决策困难，必须结合 Latest-5 可解率解释。

## Recommendation

采用“both、数据优先”的决策：先补充独立、人工复核、Latest-5 无法凭倒序覆盖的 temporal-hard 开发/验证任务，再在现有 hard strata 上修正算法。原因是当前 benchmark 的模板重复和 recency coverage 会显著稀释难度；同时若 TMC-RAG-v2 (frozen) 在现有 hard strata 没有稳定胜过简单基线，也不能只归因于数据过易。禁止在 dev 上按结果删题或继续调权重后覆盖本审计。

## Limitations

- 标签规则是设计语义审计，不是专家逐 query 复标；`CROSS_SOURCE_REQUIRED` 用必要证据跨 record kind/asset 的保守定义。
- query 级百分比包含成对改写；论文统计应按 intent 或 asset/chain 聚类给区间。
- 只评检索 Recall/nDCG/Complete，不评价最终答案的因果措辞、安全性或不确定性表达。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
