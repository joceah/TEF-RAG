"""Stage 2C relation-vs-selection bottleneck attribution; no algorithm changes."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage2a import build_runtime
from scripts.run_tef_rag_v6_stage2b1 import flow_oracle, prepare_query, relation_graph_feasibility
from tef_rag_v6.evaluation import evaluate_prediction, flow_complete

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage2c_diagnostic.json"
DEFAULT_OUTPUT = ROOT / "results/v6/stage2c_bottleneck_attribution"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def assignments(pool_ids, gold, k=5):
    groups = gold["required_groups"]
    options = [sorted(set(group["acceptable_evidence_ids"]) & pool_ids) for group in groups]
    if any(not row for row in options):
        return
    group_ids = [group["group_id"] for group in groups]
    for values in product(*options):
        if len(set(values)) <= k:
            yield dict(zip(group_ids, values))


def assignment_satisfies(assignment, gold, predicate):
    return all(predicate(assignment[e["from_group"]], assignment[e["to_group"]], e)
               for e in gold["required_flow_edges"])


def feasible_assignments(pool_ids, gold, predicate, k=5):
    return [a for a in assignments(pool_ids, gold, k) if assignment_satisfies(a, gold, predicate)]


def official_predicate(source, target, edge):
    return [source, target] in edge["allowed_endpoint_pairs"]


def matrix_category(relation_feasible, actual):
    if relation_feasible and actual:
        return "A_relation_yes_actual_yes"
    if relation_feasible:
        return "B_relation_yes_actual_no"
    if actual:
        return "C_relation_no_actual_yes"
    return "D_relation_no_actual_no"


def objective_category(greedy_score, feasible_score, tolerance=1e-12):
    gap = greedy_score - feasible_score
    if gap > tolerance:
        return "objective_misalignment"
    if gap < -tolerance:
        return "search_failure_under_current_objective"
    return "other_ambiguous"


def funnel_flags(pool_ids, gold, pair_set, accepted_pairs, typed_edges):
    official = feasible_assignments(pool_ids, gold, official_predicate)
    prefilter = feasible_assignments(pool_ids, gold,
        lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t) in pair_set)
    has_edge = feasible_assignments(pool_ids, gold,
        lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t) in accepted_pairs)
    typed = feasible_assignments(pool_ids, gold,
        lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and
                         (s, t, e["relation_type"]) in typed_edges)
    return official, prefilter, has_edge, typed


def selector_attribution(retriever, query, prediction, gold, typed_assignments):
    if not typed_assignments:
        return None
    node_scores = prediction["_all_node_scores"]
    edges = prediction["relation_graph"]
    demands = retriever._role_demands(retriever._public_query(query)["query_text"])
    greedy_ids = tuple(prediction["selected_evidence_ids"])
    greedy_score = retriever._set_score(greedy_ids, node_scores, edges, demands,
                                        use_relations=True)["total"]
    pool_order = prediction["search_diagnostics"]["search_pool_ids"]
    ranks = {identifier: index + 1 for index, identifier in enumerate(pool_order)}
    candidates = []
    for assignment in typed_assignments:
        ids = tuple(sorted(set(assignment.values())))
        score = retriever._set_score(ids, node_scores, edges, demands, use_relations=True)["total"]
        candidates.append((score, ids))
    best_score, best_ids = sorted(candidates, key=lambda x: (-x[0], x[1]))[0]
    overlap = len(set(greedy_ids) & set(best_ids))
    gap = greedy_score - best_score
    category = objective_category(greedy_score, best_score)
    return {"category": category, "greedy_score": greedy_score,
            "best_feasible_set_score": best_score, "greedy_minus_feasible": gap,
            "max_required_rank": max(ranks[i] for i in best_ids),
            "mean_required_rank": statistics.fmean(ranks[i] for i in best_ids),
            "selected_overlap": overlap, "missing_required_evidence": len(best_ids) - overlap}


def freeze_payload(raw, prompt_version):
    keys = ("attribution_definition_version", "funnel_definition_version",
            "selector_score_diagnostic_version", "relation_type_breakdown_version")
    return {"status": "FROZEN_AFTER_DEVELOPMENT",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_stage2b1_commit": raw["base_stage2b1_commit"],
            "pipeline_mode": raw["pipeline_mode"],
            "relation_prompt_version": prompt_version,
            "relation_cache_fingerprint_version": "stage2a-pair-cache-v1",
            **{key: raw[key] for key in keys},
            "definition_hash": digest({key: raw[key] for key in keys})}


def rate(count, total):
    return count / total if total else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    parser.add_argument("--sanity", type=int, default=0)
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    b1 = json.loads((ROOT / raw["stage2b1_config"]).read_text(encoding="utf-8"))
    _, base, _, client, retriever = build_runtime(ROOT / b1["stage2a_config"])
    retriever.config = replace(base, search_pool_k=b1["search_pool_k"], **b1["beam"])
    if args.split == "validation":
        path = args.output / "diagnostic_freeze.json"
        if not path.exists():
            raise SystemExit("validation requires diagnostic_freeze.json")
        frozen, current = json.loads(path.read_text(encoding="utf-8")), freeze_payload(raw, client.config.prompt_version)
        for key in current:
            if key != "frozen_at_utc" and frozen[key] != current[key]:
                raise SystemExit(f"diagnostic definition changed after development: {key}")
    queries, gold_by_id = load_inputs(args.split)
    if args.sanity:
        if args.split != "development":
            raise SystemExit("sanity is development-only")
        queries = queries[:args.sanity]

    cache_fingerprints = {path.stem for path in client.cache_dir.rglob("*.json")}
    prepared = {}
    cached = 0
    for query in queries:
        public, eligible, scores, pool, pairs = prepare_query(retriever, query, "improved")
        for pair in pairs:
            fp = client.fingerprint(public, pair["source"], pair["target"])
            if fp not in cache_fingerprints:
                raise SystemExit("cache preflight failed; Stage 2C forbids HTTP")
            cached += 1
        prepared[query["query_id"]] = (public, eligible, scores, pool, pairs)
    client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("Stage2C HTTP forbidden"))

    matrix, funnel, d_attr, b_attr = Counter(), Counter(), Counter(), Counter()
    matrix_examples, d_examples, b_examples = defaultdict(list), defaultdict(list), defaultdict(list)
    type_stats = defaultdict(Counter)
    selector_values = defaultdict(list)
    baseline_metrics = []
    for index, query in enumerate(queries, 1):
        gold = gold_by_id[query["query_id"]]
        public, eligible, scores, pool, pairs = prepared[query["query_id"]]
        pool_ids = {item["document"]["evidence_id"] for item in pool}
        prediction = retriever.retrieve(query, relation_mode="llm", search_mode="greedy",
                                        prefilter_mode="improved")
        rd = prediction["relation_diagnostics"]
        if rd.get("llm_called_pair_count") or rd.get("request_count"):
            raise SystemExit("forbidden new LLM request attempted")
        prediction["_all_node_scores"] = scores
        pair_set = {(p["source"]["evidence_id"], p["target"]["evidence_id"]) for p in pairs}
        accepted_pairs = {(e["source_id"], e["target_id"]) for e in prediction["relation_graph"]}
        typed_edges = {(e["source_id"], e["target_id"], e["relation_type"])
                       for e in prediction["relation_graph"]}
        official, prefilter, has_edge, typed = funnel_flags(
            pool_ids, gold, pair_set, accepted_pairs, typed_edges)
        actual = flow_complete(prediction["selected_evidence_ids"], gold)
        relation_feasible = bool(typed)
        category = matrix_category(relation_feasible, actual)
        matrix[category] += 1
        if len(matrix_examples[category]) < 5:
            matrix_examples[category].append(query["query_id"])
        funnel.update(search_flow=bool(official), prefilter=bool(prefilter),
                      has_edge=bool(has_edge), typed=relation_feasible, actual=actual)
        if category == "D_relation_no_actual_no":
            if not official:
                reason = "other_global_consistency"
            elif not prefilter:
                reason = "prefilter_pair_missing"
            elif not has_edge:
                reason = "llm_no_edge_or_low_confidence"
            elif not typed:
                reason = "wrong_relation_type"
            else:
                reason = "other_global_consistency"
            d_attr[reason] += 1
            if len(d_examples[reason]) < 5:
                d_examples[reason].append(query["query_id"])
        if category == "B_relation_yes_actual_no":
            detail = selector_attribution(retriever, query, prediction, gold, typed)
            b_attr[detail["category"]] += 1
            if len(b_examples[detail["category"]]) < 5:
                b_examples[detail["category"]].append(query["query_id"])
            for key, value in detail.items():
                if key != "category":
                    selector_values[key].append(value)
        for edge in gold["required_flow_edges"]:
            relation = edge["relation_type"]
            allowed = [tuple(pair) for pair in edge["allowed_endpoint_pairs"]]
            type_stats[relation]["gold_edges"] += 1
            type_stats[relation]["prefilter_hits"] += any(pair in pair_set for pair in allowed)
            type_stats[relation]["has_edge_hits"] += any(pair in accepted_pairs for pair in allowed)
            type_stats[relation]["typed_hits"] += any((s, t, relation) in typed_edges for s, t in allowed)
        baseline_metrics.append(evaluate_prediction(prediction, gold, retriever.config.final_k))
        if index % 40 == 0 or index == len(queries):
            print(f"{args.split}: {index}/{len(queries)}", flush=True)

    count = len(queries)
    relation_yes = matrix["A_relation_yes_actual_yes"] + matrix["B_relation_yes_actual_no"]
    relation_no = matrix["C_relation_no_actual_yes"] + matrix["D_relation_no_actual_no"]
    matrix_output = {"query_count": count, "cells": {key: {"count": matrix[key], "rate": rate(matrix[key], count)}
        for key in ("A_relation_yes_actual_yes", "B_relation_yes_actual_no",
                    "C_relation_no_actual_yes", "D_relation_no_actual_no")},
        "conditional_rates": {
            "actual_success_given_relation_feasible": rate(matrix["A_relation_yes_actual_yes"], relation_yes),
            "selection_failure_given_feasible": rate(matrix["B_relation_yes_actual_no"], relation_yes),
            "success_despite_relation_infeasible": rate(matrix["C_relation_no_actual_yes"], relation_no),
            "actual_failure_given_relation_infeasible": rate(matrix["D_relation_no_actual_no"], relation_no)},
        "representative_query_ids": dict(matrix_examples)}
    stages = [("search_flow_oracle", funnel["search_flow"]),
              ("prefilter_endpoint_feasible", funnel["prefilter"]),
              ("llm_has_edge_feasible", funnel["has_edge"]),
              ("typed_relation_feasible", funnel["typed"]),
              ("actual_flow_complete", funnel["actual"])]
    funnel_output = {"query_count": count, "stages": {}, "adjacent_drops": {}}
    for name, value in stages:
        funnel_output["stages"][name] = {"count": value, "rate": rate(value, count)}
    for (left, a), (right, b) in zip(stages, stages[1:]):
        funnel_output["adjacent_drops"][f"{left}_to_{right}"] = {
            "absolute_drop": a - b, "percentage_point_drop": 100 * rate(a - b, count)}
    relation_failure = {"query_count_D": matrix["D_relation_no_actual_no"],
                        "counts": dict(d_attr), "representative_query_ids": dict(d_examples)}
    selector_failure = {"query_count_B": matrix["B_relation_yes_actual_no"],
                        "counts": dict(b_attr), "representative_query_ids": dict(b_examples),
                        "diagnostic_means": {key: statistics.fmean(values) if values else None
                                             for key, values in selector_values.items()}}
    relation_types = {name: {"gold_edges": values["gold_edges"],
        "prefilter_endpoint_recall": rate(values["prefilter_hits"], values["gold_edges"]),
        "has_edge_recall": rate(values["has_edge_hits"], values["gold_edges"]),
        "correct_type_recall": rate(values["typed_hits"], values["gold_edges"])}
        for name, values in sorted(type_stats.items())}
    metrics = {key: sum(row[key] for row in baseline_metrics) / count for key in baseline_metrics[0]}
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {"relation_selection_matrix": matrix_output, "relation_funnel": funnel_output,
                 "relation_failure_attribution": relation_failure,
                 "selector_failure_attribution": selector_failure,
                 "relation_type_breakdown": relation_types}
    for name, value in artifacts.items():
        write_json(args.output / f"{name}_{args.split}.json", value)
    write_json(args.output / "config.json", raw)
    if args.split == "development" and not args.sanity:
        write_json(args.output / "diagnostic_freeze.json", freeze_payload(raw, client.config.prompt_version))
    payload = {**artifacts, "baseline_metrics": metrics, "cached_judgments_reused": cached,
               "new_llm_calls": 0, "cache_hit_rate": 1.0}
    if not args.sanity:
        path = args.output / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1", "splits": {},
            "test_gold_accessed": False, "sealed_test_evaluator_accessed": False,
            "private_test_artifact_accessed": False, "target_method_test_runs": 0,
            "benchmark_issue": "BENCHMARK_ISSUE_FOUND", "deployment_metadata_assumption": "chain_id"}
        summary["splits"][args.split] = payload
        write_json(path, summary)
    print(json.dumps({"matrix": matrix_output, "funnel": funnel_output,
                      "relation_failure": relation_failure, "selector_failure": selector_failure,
                      "baseline_metrics": metrics, "cached": cached, "new_llm_calls": 0},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
