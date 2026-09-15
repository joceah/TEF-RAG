"""Run reproducible TEF-RAG v6 stage-1 development/validation experiments.

The command has no test split option and never opens test query, test chain, or
sealed evaluator artifacts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tef_rag_v6 import TEFRAGV6, V6Config, load_jsonl
from tef_rag_v6.evaluation import average, evaluate_prediction


BENCHMARK = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1"
PUBLIC = BENCHMARK / "public"
DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage1.json"
DEFAULT_OUTPUT = ROOT / "results/v6/stage1"
SPLITS = ("development", "validation")
METHODS = {
    "bm25": {"apply_temporal": False, "use_relations": False, "use_flow": False},
    "bm25_temporal": {"apply_temporal": True, "use_relations": False, "use_flow": False},
    "v6_full": {"apply_temporal": True, "use_relations": True, "use_flow": True},
    "v6_without_temporal": {"apply_temporal": False, "use_relations": True, "use_flow": True},
    "v6_without_relation": {"apply_temporal": True, "use_relations": False, "use_flow": True},
    "v6_without_flow": {"apply_temporal": True, "use_relations": False, "use_flow": False},
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_inputs(split: str) -> tuple[list[dict], dict[str, dict]]:
    if split not in SPLITS:
        raise ValueError("stage-1 runner permits development and validation only")
    queries_path = PUBLIC / f"queries_{split}.jsonl"
    gold_path = PUBLIC / f"gold_{split}.jsonl"
    if not queries_path.exists() or not gold_path.exists():
        raise SystemExit("public artifacts are absent; run scripts/materialize_tef_v6_semantic_benchmark_v1.py")
    queries = load_jsonl(queries_path)
    gold = {item["query_id"]: item for item in load_jsonl(gold_path)}
    if set(item["query_id"] for item in queries) != set(gold):
        raise ValueError(f"query/gold IDs differ for {split}")
    return queries, gold


def compact_prediction(query: dict, prediction: dict) -> dict:
    return {
        "query_id": query["query_id"],
        "selected_evidence_ids": prediction["selected_evidence_ids"],
        "ordered_evidence_flow": prediction["ordered_evidence_flow"],
        "relations": [
            {key: edge[key] for key in ("source_id", "target_id", "relation_type", "score")}
            for edge in prediction.get("relations", [])
        ],
        "flow_score": prediction["flow_score"],
        "node_scores": prediction["node_scores"],
        "uncertainty": prediction["uncertainty"],
        "candidate_count": prediction["candidate_count"],
        "eligible_count": prediction["eligible_count"],
        "rejections": prediction["rejections"],
        "rejection_reason_counts": dict(Counter(item["reason"] for item in prediction["rejections"])),
    }


def classify_failure(
    query: dict,
    gold: dict,
    prediction: dict,
    metrics: dict,
    candidate_ids: set[str],
    eligible_ids: set[str],
    retriever: TEFRAGV6,
) -> str | None:
    if metrics["complete_at_5"] == 1.0 and metrics["edge_recall"] == 1.0 and metrics["uncertainty_accuracy"] == 1.0:
        return None
    groups = gold["required_groups"]
    if any(not (candidate_ids & set(group["acceptable_evidence_ids"])) for group in groups):
        return "candidate_retrieval_miss"
    if any(not (eligible_ids & set(group["acceptable_evidence_ids"])) for group in groups):
        return "temporal_filtering_error"
    selected = prediction["selected_evidence_ids"]
    if any(
        group.get("role") == "procedure" and not (set(selected) & set(group["acceptable_evidence_ids"]))
        for group in groups
    ):
        return "procedure_applicability_error"
    if metrics["complete_at_5"] == 1.0 and metrics["edge_recall"] < 1.0:
        return "relation_classification_error"
    if metrics["uncertainty_accuracy"] < 1.0:
        return "uncertainty_handling_error"
    pairs = [
        retriever._similarity(left, right)
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
    ]
    if pairs and max(pairs) > 0.72:
        return "evidence_redundancy"
    if all(eligible_ids & set(group["acceptable_evidence_ids"]) for group in groups):
        return "flow_search_error"
    return "insufficient_required_group_coverage"


def run_split(split: str, retriever: TEFRAGV6, output: Path) -> tuple[dict, dict]:
    queries, gold_by_id = load_inputs(split)
    metric_rows: dict[str, list[dict]] = {method: [] for method in METHODS}
    full_predictions: list[dict] = []
    failures = Counter()
    examples: dict[str, list[str]] = {}
    candidate_counts, eligible_counts, rejected_counts = [], [], []
    started = time.perf_counter()
    for position, query in enumerate(queries, 1):
        gold = gold_by_id[query["query_id"]]
        raw_candidates = retriever.candidate_retrieval(query)
        candidate_ids = {item["document"]["evidence_id"] for item in raw_candidates}
        eligible_ids = {
            item["document"]["evidence_id"]
            for item in raw_candidates
            if retriever.temporal_eligibility(item["document"], retriever._public_query(query))[0]
        }
        predictions = {}
        for method, options in METHODS.items():
            prediction = retriever.retrieve(query, **options)
            predictions[method] = prediction
            metrics = evaluate_prediction(prediction, gold, retriever.config.final_k)
            invalid = sum(
                not retriever.temporal_eligibility(retriever.by_id[identifier], retriever._public_query(query))[0]
                for identifier in prediction["selected_evidence_ids"]
            )
            metrics["constraint_violation_rate"] = invalid / max(len(prediction["selected_evidence_ids"]), 1)
            metric_rows[method].append(metrics)
        full = predictions["v6_full"]
        full_predictions.append(compact_prediction(query, full))
        category = classify_failure(
            query, gold, full, metric_rows["v6_full"][-1], candidate_ids, eligible_ids, retriever
        )
        if category:
            failures[category] += 1
            examples.setdefault(category, [])
            if len(examples[category]) < 3:
                examples[category].append(query["query_id"])
        candidate_counts.append(full["candidate_count"])
        eligible_counts.append(full["eligible_count"])
        rejected_counts.append(len(full["rejections"]))
        if position % 240 == 0:
            print(f"{split}: {position}/{len(queries)}", flush=True)
    elapsed = time.perf_counter() - started
    metrics = {method: average(rows) for method, rows in metric_rows.items()}
    runtime = {
        "query_count": len(queries),
        "elapsed_seconds": elapsed,
        "queries_per_second": len(queries) / elapsed if elapsed else 0.0,
        "candidate_count_mean": statistics.fmean(candidate_counts),
        "eligible_count_mean": statistics.fmean(eligible_counts),
        "rejected_count_mean": statistics.fmean(rejected_counts),
    }
    failure_analysis = {
        "split": split,
        "category_counts": dict(failures.most_common()),
        "representative_query_ids": examples,
        "classification_priority": [
            "candidate_retrieval_miss", "temporal_filtering_error", "procedure_applicability_error",
            "relation_classification_error", "uncertainty_handling_error", "evidence_redundancy",
            "flow_search_error", "insufficient_required_group_coverage",
        ],
    }
    write_jsonl(output / f"predictions_{split}.jsonl", full_predictions)
    write_json(output / f"metrics_{split}.json", metrics)
    write_json(output / f"runtime_{split}.json", runtime)
    write_json(output / f"failure_analysis_{split}.json", failure_analysis)
    return metrics, {"runtime": runtime, "failure_analysis": failure_analysis}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", choices=("development", "validation", "both"), default="both")
    args = parser.parse_args()
    config = V6Config.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
    evidence = load_jsonl(PUBLIC / "evidence.jsonl")
    retriever = TEFRAGV6(evidence, config)
    splits = SPLITS if args.split == "both" else (args.split,)
    summary = {
        "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1",
        "benchmark_status": "FINAL_SEALED",
        "protocol_commit": "b0e6e004378e7d7f29cabece1efa6b2c30489e9b",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config.seed,
        "top_k": config.final_k,
        "test_gold_accessed": False,
        "test_evaluator_accessed": False,
        "target_method_test_runs": 0,
        "splits": {},
    }
    # Split-specific invocations compose into the same auditable summary.
    existing_summary = args.output / "summary.json"
    if args.split != "both" and existing_summary.exists():
        previous = json.loads(existing_summary.read_text(encoding="utf-8"))
        summary["splits"].update(previous.get("splits", {}))
    for split in splits:
        metrics, diagnostics = run_split(split, retriever, args.output)
        summary["splits"][split] = {"metrics": metrics, **diagnostics}
    write_json(args.output / "config.json", config.to_dict())
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
