"""Corrected Stage 2B.1 beam comparison and evaluation-only oracle diagnostics."""
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
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage2b1_correction.json"
DEFAULT_OUTPUT = ROOT / "results/v6/stage2b1_correction"
METHODS = {
    "improved_prefilter_greedy": "greedy",
    "improved_prefilter_raw_beam": "raw_beam",
    "improved_prefilter_beam_fallback": "beam_with_fallback",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def assignment_options(pool_ids, gold):
    return [sorted(set(group["acceptable_evidence_ids"]) & pool_ids)
            for group in gold["required_groups"]]


def group_oracle(pool_ids, gold, k=5):
    options = assignment_options(pool_ids, gold)
    return bool(options) and all(options) and any(len(set(values)) <= k for values in product(*options))


def flow_oracle(pool_ids, gold, k=5):
    """Official FlowComplete feasibility: gold endpoints only, no predicted graph."""
    options = assignment_options(pool_ids, gold)
    if not options or any(not row for row in options):
        return False
    group_ids = [group["group_id"] for group in gold["required_groups"]]
    for values in product(*options):
        if len(set(values)) > k:
            continue
        assignment = dict(zip(group_ids, values))
        if all([assignment[e["from_group"]], assignment[e["to_group"]]] in e["allowed_endpoint_pairs"]
               for e in gold["required_flow_edges"]):
            return True
    return False


def relation_graph_feasibility(pool_ids, graph, gold, k=5):
    options = assignment_options(pool_ids, gold)
    if not options or any(not row for row in options):
        return False
    predicted = {(e["source_id"], e["target_id"], e["relation_type"]) for e in graph}
    group_ids = [group["group_id"] for group in gold["required_groups"]]
    for values in product(*options):
        if len(set(values)) > k:
            continue
        assignment = dict(zip(group_ids, values))
        if all((assignment[e["from_group"]], assignment[e["to_group"]], e["relation_type"])
               in predicted for e in gold["required_flow_edges"]):
            return True
    return False


def quantiles(values):
    values = sorted(values)
    if not values:
        return {key: None for key in ("mean", "median", "p25", "p75", "min", "max")}
    at = lambda f: values[round((len(values) - 1) * f)]
    return {"mean": statistics.fmean(values), "median": statistics.median(values),
            "p25": at(.25), "p75": at(.75), "min": values[0], "max": values[-1]}


def freeze_payload(raw, retriever, client):
    beam = raw["beam"]
    return {"status": "FROZEN_AFTER_DEVELOPMENT",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_stage2b_commit": raw["base_stage2b_commit"],
            "search_pool_k": retriever.config.search_pool_k,
            "beam_expansion_top_k": retriever.config.expansion_top_k,
            "beam_width": retriever.config.beam_width,
            "beam_config_hash": digest(beam), "prefilter_mode": raw["prefilter_mode"],
            "relation_prompt_version": client.config.prompt_version,
            "relation_cache_fingerprint_version": "stage2a-pair-cache-v1",
            "oracle_definition_version": raw["oracle_definition_version"]}


def prepare_query(retriever, query, prefilter_mode):
    public = retriever._public_query(query)
    eligible = [item for item in retriever.candidate_retrieval(public)
                if retriever.temporal_eligibility(item["document"], public)[0]]
    scores = retriever._node_scores(public, eligible)
    pool = sorted(eligible, key=lambda item: (-scores[item["document"]["evidence_id"]]["total"],
                                               item["document"]["evidence_id"]))[:retriever.config.search_pool_k]
    pairs, _ = retriever.relation_scorer.prefilter(pool, scores, retriever._relation_kind,
                                                   retriever._similarity, prefilter_mode)
    return public, eligible, scores, pool, pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    parser.add_argument("--sanity", type=int, default=0)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    _, base, _, client, retriever = build_runtime(ROOT / raw["stage2a_config"])
    retriever.config = replace(base, search_pool_k=raw["search_pool_k"], **raw["beam"])
    assert retriever.config.expansion_top_k == retriever.config.search_pool_k
    if args.split == "validation":
        frozen_path = args.output / "development_freeze.json"
        if not frozen_path.exists():
            raise SystemExit("validation requires development freeze")
        frozen, current = json.loads(frozen_path.read_text(encoding="utf-8")), freeze_payload(raw, retriever, client)
        for key in ("base_stage2b_commit", "search_pool_k", "beam_expansion_top_k", "beam_width",
                    "beam_config_hash", "prefilter_mode", "relation_prompt_version",
                    "relation_cache_fingerprint_version", "oracle_definition_version"):
            if frozen[key] != current[key]:
                raise SystemExit(f"configuration changed after development freeze: {key}")
    queries, gold_by_id = load_inputs(args.split)
    if args.sanity:
        if args.split != "development":
            raise SystemExit("sanity is development-only")
        queries = queries[:args.sanity]

    # Strict preflight: Stage 2B.1 never invokes HTTP. Every improved-prefilter pair must exist.
    cache_fingerprints = {path.stem for path in client.cache_dir.rglob("*.json")}
    missing, cached = [], 0
    for query in queries:
        public, _, _, _, pairs = prepare_query(retriever, query, raw["prefilter_mode"])
        for pair in pairs:
            fingerprint = client.fingerprint(public, pair["source"], pair["target"])
            if fingerprint not in cache_fingerprints:
                missing.append((query["query_id"], pair["source"]["evidence_id"], pair["target"]["evidence_id"]))
            else:
                cached += 1
    if missing:
        raise SystemExit(f"cache preflight failed: {len(missing)} missing pairs; HTTP is forbidden")
    client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("Stage2B.1 HTTP forbidden"))

    metric_rows = {name: [] for name in METHODS}
    failures = {name: Counter() for name in METHODS}
    examples = {name: defaultdict(list) for name in METHODS}
    oracle_totals = Counter()
    bottlenecks = Counter()
    beam_deltas, fallback_count, raw_same, fallback_final_same = [], 0, 0, 0
    runtimes = {name: [] for name in METHODS}
    cache_hits = Counter()
    for number, query in enumerate(queries, 1):
        gold = gold_by_id[query["query_id"]]
        public, eligible, _, pool, _ = prepare_query(retriever, query, raw["prefilter_mode"])
        candidate_ids = {item["document"]["evidence_id"] for item in eligible}
        pool_ids = {item["document"]["evidence_id"] for item in pool}
        predictions = {}
        for name, mode in METHODS.items():
            started = time.perf_counter()
            prediction = retriever.retrieve(query, relation_mode="llm", search_mode=mode,
                                            prefilter_mode=raw["prefilter_mode"])
            runtimes[name].append(time.perf_counter() - started)
            predictions[name] = prediction
            assert set(prediction["search_diagnostics"]["search_pool_ids"]) == pool_ids
            metric = evaluate_prediction(prediction, gold, retriever.config.final_k)
            metric["constraint_violation_rate"] = sum(
                not retriever.temporal_eligibility(retriever.by_id[i], public)[0]
                for i in prediction["selected_evidence_ids"]) / max(len(prediction["selected_evidence_ids"]), 1)
            metric_rows[name].append(metric)
            rd = prediction["relation_diagnostics"]
            if rd.get("llm_called_pair_count") or rd.get("request_count"):
                raise SystemExit("Stage 2B.1 attempted a forbidden new LLM request")
            cache_hits[name] += rd.get("cache_hit_count", 0)
            failure = classify_failure(query, gold, prediction, metric, candidate_ids, pool_ids, retriever)
            if failure:
                failures[name][failure] += 1
                if len(examples[name][failure]) < 3:
                    examples[name][failure].append(query["query_id"])
        greedy = predictions["improved_prefilter_greedy"]
        raw_beam = predictions["improved_prefilter_raw_beam"]
        fallback = predictions["improved_prefilter_beam_fallback"]
        raw_same += raw_beam["selected_evidence_ids"] == greedy["selected_evidence_ids"]
        fallback_count += bool(fallback["search_diagnostics"]["fallback_used"])
        fallback_final_same += fallback["selected_evidence_ids"] == greedy["selected_evidence_ids"]
        beam_deltas.append(raw_beam["search_diagnostics"]["beam_score_minus_greedy_score"])
        candidate_group = group_oracle(candidate_ids, gold)
        search_group = group_oracle(pool_ids, gold)
        search_flow = flow_oracle(pool_ids, gold)
        relation_feasible = relation_graph_feasibility(pool_ids, greedy["relation_graph"], gold)
        actual = bool(flow_complete(greedy["selected_evidence_ids"], gold))
        assert (not search_group) or candidate_group
        assert (not search_flow) or search_group
        assert (not actual) or search_flow
        oracle_totals.update(candidate_group=candidate_group, search_group=search_group,
                             search_flow=search_flow, relation_feasible=relation_feasible, actual=actual)
        if not candidate_group:
            bottlenecks["type_1"] += 1
        elif not search_group:
            bottlenecks["type_2"] += 1
        elif not search_flow:
            bottlenecks["type_3"] += 1
        elif not actual:
            bottlenecks["type_4"] += 1
        if number % 40 == 0 or number == len(queries):
            print(f"{args.split}: {number}/{len(queries)}", flush=True)

    count = len(queries)
    metrics = {name: average(metric_rows[name]) for name in METHODS}
    beam = {"query_count": count, "raw_beam_selected_count": count,
            "fallback_to_greedy_count": fallback_count, "fallback_rate": fallback_count / count,
            "raw_beam_same_as_greedy_count": raw_same,
            "raw_beam_diff_from_greedy_count": count - raw_same,
            "fallback_final_same_as_greedy_count": fallback_final_same,
            "beam_score_minus_greedy_score": quantiles(beam_deltas),
            "runtime_per_query_seconds": {name: statistics.fmean(runtimes[name]) for name in METHODS}}
    oracle = {"candidate_pool_group_complete_oracle_at_5": oracle_totals["candidate_group"] / count,
              "search_pool_group_complete_oracle_at_5": oracle_totals["search_group"] / count,
              "search_pool_flow_complete_oracle_at_5": oracle_totals["search_flow"] / count,
              "relation_graph_feasibility_at_5": oracle_totals["relation_feasible"] / count,
              "actual_flow_complete_at_5": oracle_totals["actual"] / count}
    breakdown = {key: {"count": bottlenecks[key], "rate": bottlenecks[key] / count}
                 for key in ("type_1", "type_2", "type_3", "type_4")}
    failure_output = {"split": args.split, "methods": {name: {
        "category_counts": dict(failures[name]), "representative_query_ids": dict(examples[name])
    } for name in METHODS}}
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / f"metrics_{args.split}.json", metrics)
    write_json(args.output / f"beam_comparison_{args.split}.json", beam)
    write_json(args.output / f"oracle_diagnostics_{args.split}.json", oracle)
    write_json(args.output / f"bottleneck_breakdown_{args.split}.json", breakdown)
    write_json(args.output / f"failure_analysis_{args.split}.json", failure_output)
    write_json(args.output / "config.json", raw)
    if args.split == "development" and not args.sanity:
        write_json(args.output / "development_freeze.json", freeze_payload(raw, retriever, client))
    payload = {"metrics": metrics, "beam_comparison": beam, "oracle_diagnostics": oracle,
               "bottleneck_breakdown": breakdown, "cached_relation_judgments_reused": cached,
               "new_llm_calls": 0, "cache_hit_rate": 1.0}
    if not args.sanity:
        summary_path = args.output / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
            "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1", "splits": {},
            "test_gold_accessed": False, "sealed_test_evaluator_accessed": False,
            "private_test_artifact_accessed": False, "target_method_test_runs": 0}
        summary["splits"][args.split] = payload
        write_json(summary_path, summary)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
