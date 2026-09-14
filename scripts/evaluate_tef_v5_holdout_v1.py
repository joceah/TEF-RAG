"""Gold-aware evaluation of frozen TEF-RAG v5 holdout retrieval outputs.

This script performs no retrieval, embedding, graph building, or model calls.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/tef_v5_holdout_v3"
DATA_FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
RETRIEVAL_FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_retrieval_freeze_v1/retrieval_freeze_manifest.json"
INPUT = ROOT / "experiments/runs/ta_tg_input_v5_holdout_v1"
SHARED = ROOT / "experiments/runs/tef_v5_holdout_shared_v1"
TA = ROOT / "experiments/runs/ta_rag_v5_holdout_v1"
TG = ROOT / "experiments/runs/tg_rag_v5_holdout_v1"
OUT = ROOT / "experiments/analyses/tef_v5_holdout_eval_v1"
TOP_K = 5
PRIMARY_METHODS = [
    "scoped_hybrid",
    "scoped_latest",
    "tef_v5",
    "ta_rag_no_event_interval_compat",
]
DIAGNOSTIC_METHODS = ["tg_rag_official_compat"]
METHODS = PRIMARY_METHODS + DIAGNOSTIC_METHODS
LABELS = {
    "scoped_hybrid": "Scoped hybrid",
    "scoped_latest": "Scoped latest",
    "tef_v5": "TEF-RAG v5",
    "ta_rag_no_event_interval_compat": "TA-RAG（无事件区间兼容）",
    "tg_rag_official_compat": "TG-RAG（外部失败，仅诊断）",
}
METRICS = ("group_recall_at_5", "complete_at_5", "binary_ndcg_at_5")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_hashes(hashes: dict[str, str], base: Path = ROOT) -> None:
    for name, expected in hashes.items():
        path = base / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"hash mismatch: {path}")


def score(ids: list[str], groups: list[list[str]]) -> dict[str, float]:
    ids = ids[:TOP_K]
    required = {item for group in groups for item in group}
    covered = [bool(set(ids) & set(group)) for group in groups]
    dcg = sum(1 / math.log2(rank + 1) for rank, item in enumerate(ids, 1) if item in required)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(TOP_K, len(required)) + 1))
    return {
        "group_recall_at_5": sum(covered) / len(groups),
        "complete_at_5": float(all(covered)),
        "binary_ndcg_at_5": dcg / ideal if ideal else 1.0,
    }


def average(rows: list[dict]) -> dict[str, float]:
    if not rows:
        raise RuntimeError("cannot average an empty stratum")
    return {key: sum(row[key] for row in rows) / len(rows) for key in METRICS}


def load_outputs() -> tuple[dict[tuple[str, str], list[str]], dict[str, str]]:
    outputs: dict[tuple[str, str], list[str]] = {}
    evaluated_hashes: dict[str, str] = {}

    for path in sorted((SHARED / "queries").glob("*.json")):
        row = read(path)
        for method in ("scoped_hybrid", "scoped_latest", "tef_v5"):
            outputs[(row["query_id"], method)] = row["methods"][method]["evidence_ids"]
        evaluated_hashes[rel(path)] = sha(path)

    for path in sorted((TA / "queries").glob("*.json")):
        row = read(path)
        if row["temporal_parse"]["temporal_decomposition"] != [] or row["llm_requests"] != []:
            raise RuntimeError("TA run unexpectedly activated a temporal or LLM branch")
        outputs[(row["query_id"], "ta_rag_no_event_interval_compat")] = row["evidence_ids"]
        evaluated_hashes[rel(path)] = sha(path)

    tg_completion = read(TG / "completion.json")
    for snapshot_key in sorted(tg_completion["snapshot_completion_hashes"]):
        query_dir = TG / "snapshots" / snapshot_key / "queries"
        for path in sorted(query_dir.glob("*.json")):
            row = read(path)
            outputs[(row["query_id"], "tg_rag_official_compat")] = row["evidence_ids"]
            evaluated_hashes[rel(path)] = sha(path)

    return outputs, evaluated_hashes


def summary_row(metrics: list[dict], field: str, value: str, method: str) -> dict:
    subset = [
        row for row in metrics
        if row["method"] == method and (field == "all" or row[field] == value)
    ]
    return {
        "field": field,
        "value": value,
        "method": method,
        "evaluation_status": "invalid_external_failure" if method in DIAGNOSTIC_METHODS else "valid_primary",
        "queries": len(subset),
        "complete_queries": int(sum(row["complete_at_5"] for row in subset)),
        "metrics": average(subset),
    }


def markdown_table(summary: list[dict], field: str, value: str, methods: list[str]) -> list[str]:
    rows = [
        "| 方法 | Complete | Group Recall@5 | Complete@5 | binary nDCG@5 |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in methods:
        row = next(
            item for item in summary
            if item["field"] == field and item["value"] == value and item["method"] == method
        )
        rows.append(
            f"| {LABELS[method]} | {row['complete_queries']}/{row['queries']} | "
            f"{row['metrics']['group_recall_at_5']:.4f} | "
            f"{row['metrics']['complete_at_5']:.4f} | "
            f"{row['metrics']['binary_ndcg_at_5']:.4f} |"
        )
    return rows


def main() -> None:
    dataset_freeze = read(DATA_FREEZE)
    retrieval_freeze = read(RETRIEVAL_FREEZE)
    if dataset_freeze["status"] != "self_generated_holdout_frozen_without_independent_review":
        raise RuntimeError("unexpected dataset freeze status")
    if dataset_freeze["ranking_run_before_freeze"]:
        raise RuntimeError("dataset was ranked before freeze")
    if retrieval_freeze["status"] != "retrieval_outputs_frozen_before_gold_scoring":
        raise RuntimeError("retrieval outputs were not frozen")
    if retrieval_freeze["valid_primary_methods"] != PRIMARY_METHODS:
        raise RuntimeError("primary method list changed after retrieval freeze")
    verify_hashes(dataset_freeze["hashes"])
    verify_hashes(retrieval_freeze["output_hashes"])
    verify_hashes(retrieval_freeze["input_hashes"])

    shared_complete = read(SHARED / "retrieval_complete.json")
    ta_complete = read(TA / "completion.json")
    tg_complete = read(TG / "completion.json")
    if any(row.get("gold_read") is not False for row in (shared_complete, ta_complete, tg_complete)):
        raise RuntimeError("a retrieval run was not gold-free")
    if any(row.get("queries") != 16 for row in (shared_complete, ta_complete, tg_complete)):
        raise RuntimeError("retrieval output matrix is incomplete")

    queries = {row["query_id"]: row for row in lines(DATA / "queries.jsonl")}
    gold = {row["query_id"]: row for row in lines(DATA / "evaluation/gold.jsonl")}
    docs = {row["id"]: row for row in lines(DATA / "evidence.jsonl")}
    snapshots = read(INPUT / "snapshot_mapping.json")
    snapshot_for = {(row["asset_id"], row["query_time"]): key for key, row in snapshots.items()}
    if set(queries) != set(gold) or len(queries) != 16:
        raise RuntimeError("query/gold mismatch")
    if not all(len(group) == 1 for row in gold.values() for group in row["required_evidence_groups"]):
        raise RuntimeError("binary nDCG assumes singleton evidence groups")

    outputs, evaluated_hashes = load_outputs()
    expected = {(query_id, method) for query_id in queries for method in METHODS}
    if set(outputs) != expected:
        raise RuntimeError("method/query output matrix is incomplete")

    metrics: list[dict] = []
    audit: list[dict] = []
    for query_id, query in sorted(queries.items()):
        snapshot_key = snapshot_for[(query["asset_id"], query["query_time"])]
        visible = set(snapshots[snapshot_key]["visible_record_ids"])
        for method in METHODS:
            ids = outputs[(query_id, method)]
            if len(ids) > TOP_K or len(ids) != len(set(ids)) or set(ids) - visible:
                raise RuntimeError(f"invalid frozen output: {query_id}/{method}")
            if method in PRIMARY_METHODS and len(ids) != TOP_K:
                raise RuntimeError(f"primary method did not fill Top-5: {query_id}/{method}")
            for item in ids:
                doc = docs[item]
                if (
                    doc["asset_id"] != query["asset_id"]
                    or doc["event_time"] > query["query_time"]
                    or doc["available_at"] > query["query_time"]
                ):
                    raise RuntimeError(f"double-time visibility violation: {query_id}/{method}/{item}")
            status = "invalid_external_failure" if method in DIAGNOSTIC_METHODS else "valid_primary"
            metrics.append({
                "query_id": query_id,
                "case_id": gold[query_id]["case_id"],
                "task": gold[query_id]["task"],
                "method": method,
                "evaluation_status": status,
                "evidence_ids": ids,
                **score(ids, gold[query_id]["required_evidence_groups"]),
            })
            audit.append({
                "query_id": query_id,
                "method": method,
                "evaluation_status": status,
                "snapshot_key": snapshot_key,
                "candidate_count": len(visible),
                "returned": len(ids),
                "same_candidate_scope": True,
                "same_asset": True,
                "event_visible": True,
                "knowledge_visible": True,
            })

    summary = [
        summary_row(metrics, field, value, method)
        for field, value in [
            ("all", "all"),
            ("task", "complex_chain"),
            ("task", "cutoff_sensitive"),
            ("task", "latest_control"),
        ]
        for method in METHODS
    ]

    paired = []
    for scope in ("all", "complex_chain", "cutoff_sensitive", "latest_control"):
        selected = [query_id for query_id in queries if scope == "all" or gold[query_id]["task"] == scope]
        for baseline in [method for method in PRIMARY_METHODS if method != "tef_v5"]:
            for metric_name in METRICS:
                tef = {
                    row["query_id"]: row[metric_name]
                    for row in metrics if row["method"] == "tef_v5"
                }
                other = {
                    row["query_id"]: row[metric_name]
                    for row in metrics if row["method"] == baseline
                }
                deltas = [tef[query_id] - other[query_id] for query_id in selected]
                paired.append({
                    "scope": scope,
                    "baseline": baseline,
                    "metric": metric_name,
                    "queries": len(selected),
                    "mean_tef_minus_baseline": sum(deltas) / len(deltas),
                    "wins": sum(delta > 0 for delta in deltas),
                    "ties": sum(delta == 0 for delta in deltas),
                    "losses": sum(delta < 0 for delta in deltas),
                    "inferential_test": None,
                })

    tg_rows = [row for row in metrics if row["method"] == "tg_rag_official_compat"]
    compatibility = {
        "ta_rag": {
            "evaluation_status": "valid_primary_with_disclosed_compatibility_branch",
            "official_commit": ta_complete["official_commit"],
            "temporal_mechanism_activated": False,
            "official_llm_parser_succeeded": False,
            "retrieval_branch": ta_complete["compatibility"]["retrieval_branch"],
            "new_llm_requests": 0,
        },
        "tg_rag": {
            "evaluation_status": "invalid_external_failure",
            "official_commit": tg_complete["official_commit"],
            "failure": "provider_http_402_insufficient_balance",
            "failed_query_ids": retrieval_freeze["diagnostic_only_methods"]["tg_rag_official_compat"]["failed_query_ids"],
            "source_recovery_rate": sum(bool(row["evidence_ids"]) for row in tg_rows) / len(tg_rows),
            "top5_slot_fill_rate": sum(len(row["evidence_ids"]) for row in tg_rows) / (len(tg_rows) * TOP_K),
            "exact_token_usage_available": False,
            "included_in_primary_pairwise_comparison": False,
        },
    }

    OUT.mkdir(parents=True, exist_ok=False)
    write(OUT / "metrics.json", metrics)
    write(OUT / "summary.json", summary)
    write(OUT / "paired_deltas.json", paired)
    write(OUT / "retrieval_audit.json", audit)
    write(OUT / "compatibility.json", compatibility)

    all_table = markdown_table(summary, "all", "all", PRIMARY_METHODS)
    chain_table = markdown_table(summary, "task", "complex_chain", PRIMARY_METHODS)
    diagnostic_table = [
        "| 方法 | 截止题 Recall@5 | 截止题 nDCG@5 | 最新题 Recall@5 | 最新题 nDCG@5 |",
        "|---|---:|---:|---:|---:|",
    ]
    for method in PRIMARY_METHODS:
        cutoff = next(
            row for row in summary
            if row["field"] == "task" and row["value"] == "cutoff_sensitive" and row["method"] == method
        )
        latest = next(
            row for row in summary
            if row["field"] == "task" and row["value"] == "latest_control" and row["method"] == method
        )
        diagnostic_table.append(
            f"| {LABELS[method]} | {cutoff['metrics']['group_recall_at_5']:.4f} | "
            f"{cutoff['metrics']['binary_ndcg_at_5']:.4f} | "
            f"{latest['metrics']['group_recall_at_5']:.4f} | "
            f"{latest['metrics']['binary_ndcg_at_5']:.4f} |"
        )
    (OUT / "tables.md").write_text(
        "\n".join([
            "## 全部 16 题",
            "",
            *all_table,
            "",
            "## 复杂链 8 题",
            "",
            *chain_table,
            "",
            "## 诊断分层",
            "",
            *diagnostic_table,
        ]) + "\n",
        encoding="utf-8",
    )

    hybrid_pair = next(
        row for row in paired
        if row["scope"] == "complex_chain"
        and row["baseline"] == "scoped_hybrid"
        and row["metric"] == "group_recall_at_5"
    )
    chain_by_method = {
        row["method"]: row
        for row in summary if row["field"] == "task" and row["value"] == "complex_chain"
    }
    tef_chain = chain_by_method["tef_v5"]
    hybrid_chain = chain_by_method["scoped_hybrid"]
    recall_delta = tef_chain["metrics"]["group_recall_at_5"] - hybrid_chain["metrics"]["group_recall_at_5"]
    ndcg_delta = tef_chain["metrics"]["binary_ndcg_at_5"] - hybrid_chain["metrics"]["binary_ndcg_at_5"]
    conclusion = (
        f"在 8 道复杂链题上，TEF-RAG v5 相对 Scoped hybrid 的 Group Recall@5 差值为 "
        f"{recall_delta:+.4f}，binary nDCG@5 差值为 {ndcg_delta:+.4f}；逐题 Recall 为 "
        f"{hybrid_pair['wins']} 胜、{hybrid_pair['ties']} 平、{hybrid_pair['losses']} 负。"
    )
    report = "\n".join([
        "# TEF-RAG v5 小规模冻结 holdout 检索评价",
        "",
        conclusion,
        "",
        "这只是 4 个案例、16 道纯合成且未经独立人工审查的机制验证，不构成通用优势、统计显著性或论文创新证据。",
        "",
        "## 全部 16 题",
        "",
        *all_table,
        "",
        "## 核心复杂链 8 题",
        "",
        *chain_table,
        "",
        "## 截止与最新诊断题",
        "",
        *diagnostic_table,
        "",
        "## 运行与解释边界",
        "",
        "- 数据在检索前冻结；全部检索输出又在 gold-aware 评分前以 59 个文件哈希二次封存。",
        "- 四个主比较方法共享逐题相同的同资产、双时间可见候选范围（8 或 12 条）和 Top-5；没有削减基线候选。",
        "- TA-RAG 使用已披露的官方无事件区间兼容分支，时间解析机制未激活；它是有效的固定兼容运行，但不等同于官方端到端时间解析结果。",
        "- TG-RAG 后 5 题因外部模型 HTTP 402 余额不足返回 0 条，已原样封存并标记为无效外部失败；其描述性分数不进入主比较，也不作为 v5 优势证据。",
        "- 未运行旧 98 题，未评价最终回答生成，未做参数调整或显著性检验。",
    ])
    (OUT / "report_zh.md").write_text(report + "\n", encoding="utf-8")

    completion_inputs = {
        rel(path): sha(path)
        for path in [
            Path(__file__).resolve(),
            DATA_FREEZE,
            RETRIEVAL_FREEZE,
            SHARED / "retrieval_complete.json",
            TA / "completion.json",
            TG / "completion.json",
            INPUT / "snapshot_mapping.json",
            DATA / "queries.jsonl",
            DATA / "evidence.jsonl",
            DATA / "evaluation/gold.jsonl",
        ]
    }
    write(OUT / "completion.json", {
        "status": "complete_with_tg_external_failure_excluded_from_primary",
        "dataset": "tef_v5_holdout_v3",
        "dataset_review_status": "self_generated_frozen_without_independent_review",
        "queries": len(queries),
        "primary_methods": PRIMARY_METHODS,
        "diagnostic_only_methods": DIAGNOSTIC_METHODS,
        "top_k": TOP_K,
        "retrieval_calls": 0,
        "model_calls": 0,
        "gold_read_during_evaluation": True,
        "authoring_read": False,
        "old_98_rerun": False,
        "final_answer_generation_evaluated": False,
        "input_hashes": completion_inputs,
        "evaluated_retrieval_output_hashes": evaluated_hashes,
        "output_hashes": {
            name: sha(OUT / name)
            for name in [
                "metrics.json",
                "summary.json",
                "paired_deltas.json",
                "retrieval_audit.json",
                "compatibility.json",
                "tables.md",
                "report_zh.md",
            ]
        },
    })
    print("\n".join(chain_table))
    print(conclusion)


if __name__ == "__main__":
    main()
