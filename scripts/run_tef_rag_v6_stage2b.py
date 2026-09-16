"""Stage 2B beam/prefilter ablation runner; public development/validation only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from itertools import product
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_tef_rag_v6_stage1 import classify_failure, load_inputs, write_json
from scripts.run_tef_rag_v6_stage2a import build_runtime
from tef_rag_v6.evaluation import average, evaluate_prediction

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage2b_beam_search.json"
DEFAULT_OUTPUT = ROOT / "results/v6/stage2b_beam_search"
METHODS = {
    "stage2a_llm_greedy": ("greedy", "stage2a"),
    "stage2a_llm_beam": ("beam", "stage2a"),
    "improved_prefilter_greedy": ("greedy", "improved"),
    "improved_prefilter_beam": ("beam", "improved"),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def oracle(candidate_ids, graph, gold, k=5):
    options = [sorted(set(group["acceptable_evidence_ids"]) & candidate_ids)
               for group in gold["required_groups"]]
    if any(not row for row in options):
        return False, False
    graph_edges = {(e["source_id"], e["target_id"], e["relation_type"]) for e in graph}
    candidate_ok = relation_ok = False
    group_ids = [group["group_id"] for group in gold["required_groups"]]
    for values in product(*options):
        if len(set(values)) > k:
            continue
        candidate_ok = True
        assignment = dict(zip(group_ids, values))
        if all((assignment[e["from_group"]], assignment[e["to_group"]], e["relation_type"])
               in graph_edges for e in gold["required_flow_edges"]):
            relation_ok = True
            break
    return candidate_ok, relation_ok


def freeze_payload(raw, client):
    return {
        "status": "FROZEN_AFTER_DEVELOPMENT",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_stage2a_commit": raw["base_stage2a_commit"],
        "beam_config_sha256": digest(raw["beam"]),
        "prefilter_config_sha256": digest(raw["prefilter"]),
        "relation_prompt_version": client.config.prompt_version,
        "relation_cache_fingerprint_version": "stage2a-pair-cache-v1",
        "candidate_config": "configs/tef_rag_v6_stage1.json",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    parser.add_argument("--methods", nargs="*", choices=tuple(METHODS), default=list(METHODS))
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    _, base, _, client, retriever = build_runtime(ROOT / raw["stage2a_config"])
    retriever.config = replace(base, **raw["beam"])
    if args.split == "validation":
        path = args.output / "development_freeze.json"
        if not path.exists():
            raise SystemExit("validation requires frozen development configuration")
        frozen, current = json.loads(path.read_text(encoding="utf-8")), freeze_payload(raw, client)
        for key in ("base_stage2a_commit", "beam_config_sha256", "prefilter_config_sha256",
                    "relation_prompt_version", "candidate_config"):
            if frozen[key] != current[key]:
                raise SystemExit(f"configuration changed after development freeze: {key}")
    queries, gold_by_id = load_inputs(args.split)
    warm_diagnostics = {}
    if any(METHODS[name][1] == "improved" for name in args.methods):
        cases = []
        for query in queries:
            public = retriever._public_query(query)
            eligible = [item for item in retriever.candidate_retrieval(public)
                        if retriever.temporal_eligibility(item["document"], public)[0]]
            if not eligible:
                continue
            node_scores = retriever._node_scores(public, eligible)
            relation_pool = sorted(
                eligible, key=lambda item: (-node_scores[item["document"]["evidence_id"]]["total"],
                                             item["document"]["evidence_id"])
            )[:retriever.config.search_pool_k]
            pairs, _ = retriever.relation_scorer.prefilter(
                relation_pool, node_scores, retriever._relation_kind, retriever._similarity, "improved")
            if pairs:
                cases.append({"case_id": digest(public)[:12], "query": public, "pairs": pairs})
        warm_diagnostics = client.warm_cases(cases)
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(args.output / f"cache_warm_{args.split}.json", warm_diagnostics)
        if warm_diagnostics.get("failed_batch_count"):
            raise SystemExit("improved prefilter cache warm failed; rerun resumes cached successes")
    rows = {name: [] for name in args.methods}
    failures = {name: Counter() for name in args.methods}
    examples = {name: defaultdict(list) for name in args.methods}
    diag = {name: Counter() for name in args.methods}
    runtimes = {name: [] for name in args.methods}
    oracles = {name: Counter() for name in args.methods}
    for number, query in enumerate(queries, 1):
        raw_candidates = retriever.candidate_retrieval(query)
        public = retriever._public_query(query)
        candidate_ids = {x["document"]["evidence_id"] for x in raw_candidates}
        eligible_ids = {x["document"]["evidence_id"] for x in raw_candidates
                        if retriever.temporal_eligibility(x["document"], public)[0]}
        gold = gold_by_id[query["query_id"]]
        for name in args.methods:
            search_mode, prefilter_mode = METHODS[name]
            started = time.perf_counter()
            prediction = retriever.retrieve(query, relation_mode="llm", search_mode=search_mode,
                                            prefilter_mode=prefilter_mode)
            runtimes[name].append(time.perf_counter() - started)
            metric = evaluate_prediction(prediction, gold, retriever.config.final_k)
            metric["constraint_violation_rate"] = sum(
                not retriever.temporal_eligibility(retriever.by_id[i], public)[0]
                for i in prediction["selected_evidence_ids"]
            ) / max(len(prediction["selected_evidence_ids"]), 1)
            rows[name].append(metric)
            rd, sd = prediction["relation_diagnostics"], prediction["search_diagnostics"]
            for key in ("prefiltered_pair_count", "cache_lookup_count", "cache_hit_count",
                        "llm_called_pair_count", "request_count", "accepted_edge_count"):
                diag[name][key] += rd.get(key, 0)
            diag[name]["states_expanded"] += sd["states_expanded"]
            diag[name]["surviving_states"] += sd["surviving_states"]
            failure = classify_failure(query, gold, prediction, metric, candidate_ids, eligible_ids, retriever)
            if failure:
                failures[name][failure] += 1
                if len(examples[name][failure]) < 3:
                    examples[name][failure].append(query["query_id"])
            candidate_ok, relation_ok = oracle(eligible_ids, prediction["relation_graph"], gold)
            oracles[name]["candidate"] += candidate_ok
            oracles[name]["relation"] += relation_ok
        if number % 40 == 0 or number == len(queries):
            print(f"{args.split}: {number}/{len(queries)}", flush=True)
    count = len(queries)
    metrics = {name: average(rows[name]) for name in args.methods}
    diagnostics = {}
    for name in args.methods:
        lookups = diag[name]["cache_lookup_count"]
        diagnostics[name] = {
            "queries": count,
            "runtime_per_query_seconds": statistics.fmean(runtimes[name]),
            "states_expanded_per_query": diag[name]["states_expanded"] / count,
            "surviving_states_per_query": diag[name]["surviving_states"] / count,
            "pairs_per_query": diag[name]["prefiltered_pair_count"] / count,
            "cached_pairs_reused": diag[name]["cache_hit_count"],
            "new_relation_pairs": diag[name]["llm_called_pair_count"],
            "new_llm_http_calls": diag[name]["request_count"],
            "cache_hit_rate": diag[name]["cache_hit_count"] / lookups if lookups else None,
        }
    oracle_output = {name: {
        "candidate_oracle_complete_at_5": oracles[name]["candidate"] / count,
        "relation_graph_oracle_flow_complete_at_5": oracles[name]["relation"] / count,
        "actual_flow_complete_at_5": metrics[name]["flow_complete_at_5"],
    } for name in args.methods}
    failure_output = {"split": args.split, "methods": {name: {
        "category_counts": dict(failures[name]), "representative_query_ids": dict(examples[name])
    } for name in args.methods}}
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / f"metrics_{args.split}.json", metrics)
    write_json(args.output / f"beam_diagnostics_{args.split}.json", diagnostics)
    write_json(args.output / f"prefilter_diagnostics_{args.split}.json", diagnostics)
    write_json(args.output / f"oracle_headroom_{args.split}.json", oracle_output)
    write_json(args.output / f"failure_analysis_{args.split}.json", failure_output)
    write_json(args.output / "config.json", raw)
    if args.split == "development":
        write_json(args.output / "development_freeze.json", freeze_payload(raw, client))
    summary_path = args.output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
        "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1", "splits": {},
        "test_gold_accessed": False, "sealed_test_evaluator_accessed": False,
        "private_test_review_artifact_accessed": False, "target_method_test_runs": 0,
        "benchmark_issue": "BENCHMARK_ISSUE_FOUND: validation review hash historical mismatch; unchanged",
    }
    summary["splits"][args.split] = {"metrics": metrics, "diagnostics": diagnostics,
                                      "oracle_headroom": oracle_output, "failure_analysis": failure_output,
                                      "cache_warm_diagnostics": warm_diagnostics}
    write_json(summary_path, summary)
    print(json.dumps(summary["splits"][args.split], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
