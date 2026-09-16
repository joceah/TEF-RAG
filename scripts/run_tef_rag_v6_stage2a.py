"""Run the controlled Stage 2A query-conditioned relation experiment.

Only development and validation are accepted. Validation requires a frozen
development configuration artifact produced by this runner.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_tef_rag_v6_stage1 import PUBLIC, classify_failure, load_inputs, write_json
from tef_rag_v6 import (
    LLMRelationClient,
    LLMRelationConfig,
    QueryConditionedRelationScorer,
    TEFRAGV6,
    V6Config,
    load_jsonl,
)
from tef_rag_v6.evaluation import average, evaluate_prediction


DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage2a_llm_relation.json"
DEFAULT_OUTPUT = ROOT / "results/v6/stage2a_llm_relation"
TAXONOMY_PATH = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/metadata/relation_taxonomy.json"
SPLITS = ("development", "validation")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def quantiles(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[round((len(ordered) - 1) * fraction)]

    return {
        "count": len(values), "mean": statistics.fmean(values), "min": ordered[0],
        "p25": at(0.25), "median": at(0.5), "p75": at(0.75), "max": ordered[-1],
    }


def stratified_sanity_sample(queries: list[dict], size: int) -> list[dict]:
    by_difficulty: dict[str, list[dict]] = defaultdict(list)
    for query in queries:
        by_difficulty[str(query.get("primary_difficulty", "UNLABELED"))].append(query)
    buckets = [sorted(rows, key=lambda row: row["query_id"]) for _, rows in sorted(by_difficulty.items())]
    selected = []
    offset = 0
    while len(selected) < min(size, len(queries)):
        progressed = False
        for bucket in buckets:
            if offset < len(bucket) and len(selected) < size:
                selected.append(bucket[offset])
                progressed = True
        if not progressed:
            break
        offset += 1
    return selected


def required_edge_hits(edges: list[dict], gold: dict) -> tuple[int, int]:
    predicted = {(edge["source_id"], edge["target_id"], edge["relation_type"]) for edge in edges}
    hit = sum(
        any((pair[0], pair[1], edge["relation_type"]) in predicted for pair in edge["allowed_endpoint_pairs"])
        for edge in gold["required_flow_edges"]
    )
    return hit, len(gold["required_flow_edges"])


def prefilter_hits(pairs: list[list[str]], gold: dict) -> tuple[int, int]:
    present = {tuple(pair) for pair in pairs}
    hit = sum(
        any(tuple(pair) in present for pair in edge["allowed_endpoint_pairs"])
        for edge in gold["required_flow_edges"]
    )
    return hit, len(gold["required_flow_edges"])


def build_runtime(config_path: Path):
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    pipeline_path = ROOT / raw["pipeline_config"]
    pipeline_config = V6Config.from_dict(json.loads(pipeline_path.read_text(encoding="utf-8")))
    relation_raw = dict(raw["relation"])
    env_path = (ROOT / raw["llm_env_file"]).resolve() if raw.get("llm_env_file") else None
    if env_path:
        env_values = {}
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            env_values[name.strip()] = value.strip().strip("'\"")
        required = {"API_KEY", "ENDPOINT", "MODEL"}
        missing = sorted(required - set(env_values))
        if missing:
            raise ValueError(f"missing local.env fields: {missing}")
        os.environ["TEF_RAG_LLM_API_KEY"] = env_values["API_KEY"]
        relation_raw["endpoint"] = env_values["ENDPOINT"]
        relation_raw["model"] = env_values["MODEL"]
        if env_values.get("THINKING"):
            relation_raw["thinking"] = env_values["THINKING"]
    relation_raw["cache_dir"] = str(ROOT / relation_raw["cache_dir"])
    relation_config = LLMRelationConfig.from_dict(relation_raw)
    taxonomy_container = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    taxonomy = taxonomy_container["relation_types"]
    client = LLMRelationClient(relation_config, taxonomy)
    scorer = QueryConditionedRelationScorer(client, pipeline_config.relation_threshold)
    retriever = TEFRAGV6(load_jsonl(PUBLIC / "evidence.jsonl"), pipeline_config, relation_scorer=scorer)
    return raw, pipeline_config, relation_config, client, retriever


def run_one(query: dict, gold: dict, retriever: TEFRAGV6, modes: list[str]) -> dict:
    raw_candidates = retriever.candidate_retrieval(query)
    public_query = retriever._public_query(query)
    candidate_ids = {item["document"]["evidence_id"] for item in raw_candidates}
    eligible_ids = {
        item["document"]["evidence_id"]
        for item in raw_candidates
        if retriever.temporal_eligibility(item["document"], public_query)[0]
    }
    output = {"query_id": query["query_id"], "modes": {}}
    for mode in modes:
        prediction = retriever.retrieve(query, relation_mode=mode)
        metrics = evaluate_prediction(prediction, gold, retriever.config.final_k)
        invalid = sum(
            not retriever.temporal_eligibility(retriever.by_id[identifier], public_query)[0]
            for identifier in prediction["selected_evidence_ids"]
        )
        metrics["constraint_violation_rate"] = invalid / max(len(prediction["selected_evidence_ids"]), 1)
        graph_hit, graph_total = required_edge_hits(prediction.get("relation_graph", []), gold)
        diagnostics = dict(prediction.get("relation_diagnostics", {}))
        if mode != "heuristic":
            prefilter_hit, prefilter_total = prefilter_hits(diagnostics.get("prefilter_pairs", []), gold)
        else:
            prefilter_hit, prefilter_total = 0, 0
        failure = classify_failure(
            query, gold, prediction, metrics, candidate_ids, eligible_ids, retriever
        )
        output["modes"][mode] = {
            "metrics": metrics,
            "diagnostics": diagnostics,
            "graph_edge_hits": [graph_hit, graph_total],
            "prefilter_hits": [prefilter_hit, prefilter_total],
            "selected_edge_count": len(prediction.get("relations", [])),
            "graph_confidences": [edge["score"] for edge in prediction.get("relation_graph", [])],
            "graph_relation_types": [edge["relation_type"] for edge in prediction.get("relation_graph", [])],
            "failure": failure,
        }
    return output


def prepare_warm_cases(queries: list[dict], retriever: TEFRAGV6) -> list[dict]:
    cases = []
    scorer = retriever.relation_scorer
    for query in queries:
        public = retriever._public_query(query)
        eligible = [
            item for item in retriever.candidate_retrieval(public)
            if retriever.temporal_eligibility(item["document"], public)[0]
        ]
        if not eligible:
            continue
        node_scores = retriever._node_scores(public, eligible)
        relation_pool = sorted(
            eligible,
            key=lambda item: (-node_scores[item["document"]["evidence_id"]]["total"], item["document"]["evidence_id"]),
        )[: retriever.config.search_pool_k]
        pairs, _ = scorer.prefilter(
            relation_pool, node_scores, retriever._relation_kind, retriever._similarity
        )
        if not pairs:
            continue
        case_id = sha256_bytes(json.dumps(public, ensure_ascii=False, sort_keys=True).encode("utf-8"))[:12]
        cases.append({"case_id": case_id, "query": public, "pairs": pairs})
    return cases


def aggregate(rows: list[dict], modes: list[str], split: str) -> tuple[dict, dict, dict]:
    metrics_output = {}
    diagnostics_output = {}
    failure_output = {}
    numeric_diag_keys = (
        "raw_possible_pair_count", "prefiltered_pair_count", "llm_called_pair_count", "request_count",
        "cache_lookup_count", "cache_hit_count", "retry_count", "malformed_count", "latency_seconds",
        "prompt_tokens", "completion_tokens", "invalid_type_count", "accepted_edge_count", "no_edge_count",
        "deterministic_edge_count", "client_failure_pair_count", "padded_missing_count",
    )
    for mode in modes:
        mode_rows = [row["modes"][mode] for row in rows]
        metrics_output[mode] = average([row["metrics"] for row in mode_rows])
        totals = {key: sum(float(row["diagnostics"].get(key, 0)) for row in mode_rows) for key in numeric_diag_keys}
        graph_hits = sum(row["graph_edge_hits"][0] for row in mode_rows)
        graph_total = sum(row["graph_edge_hits"][1] for row in mode_rows)
        prefilter_hit = sum(row["prefilter_hits"][0] for row in mode_rows)
        prefilter_total = sum(row["prefilter_hits"][1] for row in mode_rows)
        confidences = [value for row in mode_rows for value in row["graph_confidences"]]
        relation_types = Counter(value for row in mode_rows for value in row["graph_relation_types"])
        requests = totals["request_count"]
        lookups = totals["cache_lookup_count"]
        judged = max(totals["cache_lookup_count"] - totals["deterministic_edge_count"], 0)
        diagnostics_output[mode] = {
            "query_count": len(rows),
            "predicted_selected_edges_per_query": sum(row["selected_edge_count"] for row in mode_rows) / max(len(rows), 1),
            "accepted_graph_edges_per_query": totals["accepted_edge_count"] / max(len(rows), 1),
            "raw_possible_pairs_per_query": totals["raw_possible_pair_count"] / max(len(rows), 1),
            "prefiltered_pairs_per_query": totals["prefiltered_pair_count"] / max(len(rows), 1),
            "llm_called_pairs": int(totals["llm_called_pair_count"]),
            "llm_called_pairs_per_query": totals["llm_called_pair_count"] / max(len(rows), 1),
            "http_request_attempts": int(requests),
            "requests_per_query": requests / max(len(rows), 1),
            "cache_hit_rate": totals["cache_hit_count"] / lookups if lookups else None,
            "retry_rate": totals["retry_count"] / requests if requests else 0.0,
            "malformed_rate": totals["malformed_count"] / requests if requests else 0.0,
            "invalid_type_count": int(totals["invalid_type_count"]),
            "client_failure_pair_count": int(totals["client_failure_pair_count"]),
            "padded_missing_count": int(totals["padded_missing_count"]),
            "average_request_latency_seconds": totals["latency_seconds"] / requests if requests else 0.0,
            "no_edge_rate": totals["no_edge_count"] / judged if judged else 0.0,
            "prompt_tokens": int(totals["prompt_tokens"]),
            "completion_tokens": int(totals["completion_tokens"]),
            "average_tokens_per_request": (
                totals["prompt_tokens"] + totals["completion_tokens"]
            ) / requests if requests else 0.0,
            "graph_edge_recall": graph_hits / graph_total if graph_total else 0.0,
            "pair_prefilter_recall": prefilter_hit / prefilter_total if prefilter_total else None,
            "confidence_distribution": quantiles(confidences),
            "relation_type_distribution": dict(relation_types.most_common()),
        }
        failures = Counter(row["failure"] for row in mode_rows if row["failure"])
        examples: dict[str, list[str]] = defaultdict(list)
        for full_row, mode_row in zip(rows, mode_rows):
            category = mode_row["failure"]
            if category and len(examples[category]) < 3:
                examples[category].append(full_row["query_id"])
        failure_output[mode] = {
            "category_counts": dict(failures.most_common()),
            "representative_query_ids": dict(examples),
        }
    return metrics_output, diagnostics_output, {"split": split, "modes": failure_output}


def freeze_payload(raw_config: dict, client: LLMRelationClient) -> dict:
    config_bytes = json.dumps(raw_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "status": "FROZEN_AFTER_DEVELOPMENT",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_sha256": sha256_bytes(config_bytes),
        "prompt_sha256": sha256_bytes(client.system_prompt.encode("utf-8")),
        "prompt_version": client.config.prompt_version,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", choices=SPLITS, default="development")
    parser.add_argument("--sanity", type=int, default=0, metavar="N")
    args = parser.parse_args()
    raw_config, pipeline_config, relation_config, client, retriever = build_runtime(args.config)
    if int(raw_config.get("workers", 1)) != 1:
        raise SystemExit("Stage 2A relation evaluation requires workers=1")
    modes = list(raw_config["relation_modes"])
    queries, gold_by_id = load_inputs(args.split)
    if args.sanity:
        if args.split != "development":
            raise SystemExit("sanity sampling is development-only")
        queries = stratified_sanity_sample(queries, args.sanity)
    elif args.split == "validation":
        freeze_path = args.output / "development_freeze.json"
        if not freeze_path.exists():
            raise SystemExit("validation requires development_freeze.json")
        frozen = json.loads(freeze_path.read_text(encoding="utf-8"))
        current = freeze_payload(raw_config, client)
        if frozen["config_sha256"] != current["config_sha256"] or frozen["prompt_sha256"] != current["prompt_sha256"]:
            raise SystemExit("Stage 2A config/prompt changed after development freeze")

    started = time.perf_counter()
    warm_diagnostics = {}
    if any(mode in {"llm", "hybrid"} for mode in modes):
        warm_diagnostics = client.warm_cases(prepare_warm_cases(queries, retriever))
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / f"cache_warm_{args.split}.json", warm_diagnostics)
        if warm_diagnostics.get("failed_batch_count"):
            raise SystemExit(
                "relation cache warm stopped after a failed serial batch; cached successes are preserved, rerun to resume"
            )
    completed = []
    for index, query in enumerate(queries, 1):
        completed.append(run_one(query, gold_by_id[query["query_id"]], retriever, modes))
        if index % 20 == 0 or index == len(queries):
            print(f"{args.split}: {index}/{len(queries)}", flush=True)
    elapsed = time.perf_counter() - started
    metrics, diagnostics, failures = aggregate(completed, modes, args.split)
    payload = {
        "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1",
        "split": args.split,
        "query_count": len(queries),
        "prompt_version": relation_config.prompt_version,
        "elapsed_seconds": elapsed,
        "metrics": metrics,
        "relation_diagnostics": diagnostics,
        "cache_warm_diagnostics": warm_diagnostics,
        "failure_analysis": failures,
        "test_gold_accessed": False,
        "test_evaluator_accessed": False,
        "target_method_test_runs": 0,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    if args.sanity:
        write_json(args.output / "sanity_development.json", payload)
    else:
        write_json(args.output / f"metrics_{args.split}.json", metrics)
        write_json(args.output / f"relation_diagnostics_{args.split}.json", diagnostics)
        write_json(args.output / f"failure_analysis_{args.split}.json", failures)
        write_json(args.output / "config.json", raw_config)
        write_json(args.output / "prompt_version.json", {
            "prompt_version": relation_config.prompt_version,
            "system_prompt": client.system_prompt,
            "prompt_sha256": sha256_bytes(client.system_prompt.encode("utf-8")),
        })
        summary_path = args.output / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
            "benchmark": payload["benchmark"], "prompt_version": relation_config.prompt_version,
            "test_gold_accessed": False, "test_evaluator_accessed": False,
            "target_method_test_runs": 0, "splits": {},
        }
        summary["splits"][args.split] = payload
        write_json(summary_path, summary)
        if args.split == "development":
            write_json(args.output / "development_freeze.json", freeze_payload(raw_config, client))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
