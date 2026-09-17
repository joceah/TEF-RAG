"""Train and evaluate the Stage 3A query-conditioned learned pair proposer."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from itertools import combinations
import hashlib
import json
import platform
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage2a import build_runtime
from scripts.run_tef_rag_v6_stage2b1 import flow_oracle, prepare_query
from scripts.run_tef_rag_v6_stage2c import feasible_assignments, official_predicate
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete
from tef_rag_v6.llm_relation import QueryConditionedRelationScorer
from tef_rag_v6.pair_proposal import FEATURE_SCHEMA_VERSION, LinearPairProposer, chronological_pairs, pair_features

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage3a_pair_proposal.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def group_split(queries, seed):
    groups = sorted({str(q["chain_id"]) for q in queries})
    tune = {g for g in groups if int(hashlib.sha256(f"{seed}:{g}".encode()).hexdigest()[:8], 16) % 5 == 0}
    train = set(groups) - tune
    return train, tune


def query_context(retriever, query):
    public = retriever._public_query(query)
    eligible = [x for x in retriever.candidate_retrieval(public)
                if retriever.temporal_eligibility(x["document"], public)[0]]
    scores = retriever._node_scores(public, eligible)
    pool = sorted(eligible, key=lambda x: (-scores[x["document"]["evidence_id"]]["total"],
                                           x["document"]["evidence_id"]))[:retriever.config.search_pool_k]
    return public, scores, pool


def gold_pair_set(gold):
    return {tuple(pair) for edge in gold["required_flow_edges"] for pair in edge["allowed_endpoint_pairs"]}


def build_training(queries, gold_by_id, retriever, allowed_groups):
    features, labels = [], []
    query_count = positives = negatives = 0
    for query in queries:
        if str(query["chain_id"]) not in allowed_groups:
            continue
        public, scores, pool = query_context(retriever, query)
        positive = gold_pair_set(gold_by_id[query["query_id"]])
        demands = retriever._role_demands(public["query_text"])
        for source, target in chronological_pairs(pool):
            features.append(pair_features(public, source, target, scores, demands))
            label = int((source["evidence_id"], target["evidence_id"]) in positive)
            labels.append(label)
            positives += label
            negatives += 1 - label
        query_count += 1
    return features, np.asarray(labels, dtype=np.int8), {
        "query_count": query_count, "positive_pairs": positives, "negative_pairs": negatives}


def train_model(features, labels, raw, metadata):
    started = time.perf_counter()
    vectorizer = DictVectorizer(sparse=True, sort=True)
    matrix = vectorizer.fit_transform(features)
    hp = raw["model_hyperparameters"]
    classifier = LogisticRegression(random_state=raw["seed"], **hp).fit(matrix, labels)
    model = LinearPairProposer(vectorizer.feature_names_, classifier.coef_[0].tolist(),
                               float(classifier.intercept_[0]), metadata)
    return model, time.perf_counter() - started


def proposal_sets(retriever, query, scores, pool, proposer, budget):
    rule, _ = retriever.relation_scorer.prefilter(pool, scores, retriever._relation_kind,
                                                   retriever._similarity, "improved")
    public = retriever._public_query(query)
    demands = retriever._role_demands(public["query_text"])
    learned = proposer.rank(public, pool, scores, demands, budget, "learned")
    hybrid = proposer.rank(public, pool, scores, demands, budget, "hybrid")
    pairset = lambda rows: {(x["source"]["evidence_id"], x["target"]["evidence_id"]) for x in rows}
    return {"rule_improved": pairset(rule), "learned": pairset(learned), "hybrid": pairset(hybrid)}


def pair_metrics(queries, gold_by_id, retriever, proposer, budget, group_filter=None):
    totals = {name: Counter() for name in ("rule_improved", "learned", "hybrid")}
    for query in queries:
        if group_filter is not None and str(query["chain_id"]) not in group_filter:
            continue
        _, scores, pool = query_context(retriever, query)
        pool_ids = {x["document"]["evidence_id"] for x in pool}
        gold = gold_by_id[query["query_id"]]
        positives = gold_pair_set(gold)
        sets = proposal_sets(retriever, query, scores, pool, proposer, budget)
        for name, proposed in sets.items():
            edge_hits = sum(any(tuple(pair) in proposed for pair in edge["allowed_endpoint_pairs"])
                            for edge in gold["required_flow_edges"])
            endpoint = bool(feasible_assignments(pool_ids, gold,
                lambda s, t, e, p=proposed: [s, t] in e["allowed_endpoint_pairs"] and (s, t) in p))
            positive_hits = len(proposed & positives)
            totals[name].update(queries=1, pairs=len(proposed), edge_hits=edge_hits,
                                gold_edges=len(gold["required_flow_edges"]), endpoint=endpoint,
                                positive_hits=positive_hits)
    output = {}
    for name, value in totals.items():
        output[name] = {"query_count": value["queries"],
            "pairs_per_query": value["pairs"] / value["queries"],
            "required_edge_pair_recall": value["edge_hits"] / value["gold_edges"],
            "prefilter_endpoint_feasibility": value["endpoint"] / value["queries"],
            "proposal_precision": value["positive_hits"] / value["pairs"],
            "proposal_positive_rate": value["positive_hits"] / value["pairs"]}
    return output


def choose_variant(curves):
    choices = []
    for budget, metrics in curves.items():
        for mode in ("learned", "hybrid"):
            m = metrics[mode]
            choices.append((m["prefilter_endpoint_feasibility"], m["required_edge_pair_recall"],
                            -budget, mode, budget))
    return sorted(choices, reverse=True)[0][-2:]


def warm_cases(queries, retriever, mode):
    cases = []
    for query in queries:
        public, scores, pool = query_context(retriever, query)
        pairs, _ = retriever.relation_scorer.prefilter(pool, scores, retriever._relation_kind,
                                                       retriever._similarity, mode, query=public)
        base_id = digest(public)[:10]
        for offset in range(0, len(pairs), 8):
            cases.append({"case_id": f"{base_id}{offset // 8:02d}", "query": public,
                          "pairs": pairs[offset:offset + 8]})
    return cases


def full5_selector_diagnostic(retriever, query, prediction, gold):
    if flow_complete(prediction["selected_evidence_ids"], gold):
        return None
    pool = prediction["search_diagnostics"]["search_pool_ids"]
    pool_ids = set(pool)
    typed = {(e["source_id"], e["target_id"], e["relation_type"]) for e in prediction["relation_graph"]}
    assignments = feasible_assignments(pool_ids, gold,
        lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t, e["relation_type"]) in typed)
    if not assignments:
        return None
    public, scores, _ = query_context(retriever, query)
    demands = retriever._role_demands(public["query_text"])
    greedy = tuple(prediction["selected_evidence_ids"])
    greedy_score = retriever._set_score(greedy, scores, prediction["relation_graph"], demands,
                                        use_relations=True)["total"]
    best = None
    for assignment in assignments:
        base = set(assignment.values())
        need = retriever.config.final_k - len(base)
        for padding in combinations([x for x in pool if x not in base], need):
            ids = tuple(sorted(base | set(padding)))
            assert len(ids) == retriever.config.final_k and flow_complete(list(ids), gold)
            score = retriever._set_score(ids, scores, prediction["relation_graph"], demands,
                                         use_relations=True)["total"]
            if best is None or (score, tuple(reversed(ids))) > (best[0], tuple(reversed(best[1]))):
                best = (score, ids)
    gap = greedy_score - best[0]
    category = "objective_misalignment" if gap > 1e-12 else (
        "search_failure_under_current_objective" if gap < -1e-12 else "ambiguous_tie")
    return category, gap


def evaluate_downstream(split, queries, gold_by_id, retriever, modes):
    metrics, funnels, matrices, selector = {m: [] for m in modes}, {m: Counter() for m in modes}, \
        {m: Counter() for m in modes}, {m: Counter() for m in modes}
    cache = {m: Counter() for m in modes}
    type_stats = {m: {} for m in modes}
    for index, query in enumerate(queries, 1):
        _, scores, pool = query_context(retriever, query)
        pool_ids = {x["document"]["evidence_id"] for x in pool}
        gold = gold_by_id[query["query_id"]]
        for name, prefilter_mode in modes.items():
            prediction = retriever.retrieve(query, relation_mode="llm", search_mode="greedy",
                                            prefilter_mode=prefilter_mode)
            metrics[name].append(evaluate_prediction(prediction, gold, retriever.config.final_k))
            rd = prediction["relation_diagnostics"]
            cache[name].update(hits=rd.get("cache_hit_count", 0), calls=rd.get("llm_called_pair_count", 0),
                               requests=rd.get("request_count", 0), prompt_tokens=rd.get("prompt_tokens", 0),
                               completion_tokens=rd.get("completion_tokens", 0), lookups=rd.get("cache_lookup_count", 0))
            proposed = {tuple(x) for x in rd["prefilter_pairs"]}
            accepted = {(e["source_id"], e["target_id"]) for e in prediction["relation_graph"]}
            typed = {(e["source_id"], e["target_id"], e["relation_type"]) for e in prediction["relation_graph"]}
            for edge in gold["required_flow_edges"]:
                relation_type = edge["relation_type"]
                row = type_stats[name].setdefault(relation_type, Counter())
                allowed = {tuple(pair) for pair in edge["allowed_endpoint_pairs"]}
                row["gold_edges"] += 1
                row["prefilter_endpoint_hits"] += bool(allowed & proposed)
                row["has_edge_hits"] += bool(allowed & accepted)
                row["correct_type_hits"] += any((s, t, relation_type) in typed for s, t in allowed)
            official = flow_oracle(pool_ids, gold)
            pair_feasible = bool(feasible_assignments(pool_ids, gold,
                lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t) in proposed))
            edge_feasible = bool(feasible_assignments(pool_ids, gold,
                lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t) in accepted))
            typed_feasible = bool(feasible_assignments(pool_ids, gold,
                lambda s, t, e: [s, t] in e["allowed_endpoint_pairs"] and (s, t, e["relation_type"]) in typed))
            actual = flow_complete(prediction["selected_evidence_ids"], gold)
            funnels[name].update(search_flow=official, pair=pair_feasible, edge=edge_feasible, typed=typed_feasible)
            matrices[name].update(relation_yes_actual_yes=typed_feasible and actual,
                                  relation_yes_actual_no=typed_feasible and not actual,
                                  relation_no_actual_yes=not typed_feasible and actual,
                                  relation_no_actual_no=not typed_feasible and not actual)
            if typed_feasible and not actual:
                detail = full5_selector_diagnostic(retriever, query, prediction, gold)
                selector[name][detail[0]] += 1
        if index % 40 == 0 or index == len(queries):
            print(f"{split}: {index}/{len(queries)}", flush=True)
    count = len(queries)
    return ({m: average(rows) for m, rows in metrics.items()},
            {m: {k: {"count": v, "rate": v / count} for k, v in values.items()} for m, values in funnels.items()},
            {m: dict(values) for m, values in matrices.items()}, {m: dict(values) for m, values in selector.items()},
            {m: dict(values) for m, values in cache.items()},
            {m: {relation_type: {"gold_edges": row["gold_edges"],
                                 "prefilter_endpoint_recall": row["prefilter_endpoint_hits"] / row["gold_edges"],
                                 "has_edge_recall": row["has_edge_hits"] / row["gold_edges"],
                                 "correct_type_recall": row["correct_type_hits"] / row["gold_edges"]}
                 for relation_type, row in sorted(rows.items())} for m, rows in type_stats.items()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    b1 = json.loads((ROOT / raw["stage2b1_config"]).read_text(encoding="utf-8"))
    _, base, _, client, retriever = build_runtime(ROOT / b1["stage2a_config"])
    # Single-case compact requests are required for stable structured output from
    # the frozen relation service; each case is capped at eight pairs below.
    client.config = replace(client.config, cases_per_request=1)
    retriever.config = replace(base, search_pool_k=b1["search_pool_k"], **b1["beam"])
    output = ROOT / raw["output_dir"]
    artifact = ROOT / raw["artifact_dir"]
    model_path = artifact / "model.json"
    queries, gold_by_id = load_inputs(args.split)

    resume_development = (args.split == "development" and model_path.exists()
                          and (output / "development_freeze.json").exists()
                          and (output / "training_summary.json").exists())
    if args.split == "development" and not resume_development:
        train_groups, tune_groups = group_split(queries, raw["seed"])
        train_features, train_labels, train_stats = build_training(queries, gold_by_id, retriever, train_groups)
        metadata = {"feature_schema_version": FEATURE_SCHEMA_VERSION, "seed": raw["seed"],
                    "training_groups": len(train_groups), "tune_groups": len(tune_groups)}
        tune_model, tune_time = train_model(train_features, train_labels, raw, metadata)
        curves = {budget: pair_metrics(queries, gold_by_id, retriever, tune_model, budget, tune_groups)
                  for budget in raw["budgets"]}
        mode, budget = choose_variant(curves)
        all_groups = train_groups | tune_groups
        all_features, all_labels, all_stats = build_training(queries, gold_by_id, retriever, all_groups)
        model, final_time = train_model(all_features, all_labels, raw, {**metadata, "frozen_mode": mode,
                                        "frozen_budget": budget, "trained_all_development": True})
        model.save(model_path)
        feature_schema = {"version": FEATURE_SCHEMA_VERSION, "feature_names": model.feature_names,
                          "forbidden_features": ["chain_id", "query_id", "gold", "required_groups",
                                                 "required_flow_edges", "difficulty", "split"]}
        write_json(artifact / "feature_schema.json", feature_schema)
        training_summary = {"python_version": platform.python_version(), "sklearn_version": sklearn.__version__,
            "seed": raw["seed"], "group_split_hash": digest({"train": sorted(train_groups), "tune": sorted(tune_groups)}),
            "train_groups": len(train_groups), "tune_groups": len(tune_groups),
            "train_stats": train_stats, "all_development_stats": all_stats,
            "tune_training_seconds": tune_time, "final_training_seconds": final_time,
            "proposal_only_tune_curves": curves, "frozen_mode": mode, "frozen_budget": budget,
            "feature_schema_hash": digest(feature_schema), "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}
        write_json(output / "training_summary.json", training_summary)
        freeze = {"status": "FROZEN_AFTER_DEVELOPMENT", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_stage2c_commit": raw["base_stage2c_commit"], "training_split_hash": training_summary["group_split_hash"],
            "feature_schema_hash": training_summary["feature_schema_hash"], "model_type": raw["model_type"],
            "model_hyperparameters": raw["model_hyperparameters"], "proposal_mode": mode, "pair_budget": budget,
            "relation_prompt_version": client.config.prompt_version,
            "relation_confidence_threshold": client.config.llm_confidence_threshold,
            "candidate_k": retriever.config.candidate_k, "search_pool_k": retriever.config.search_pool_k,
            "random_seed": raw["seed"], "model_sha256": training_summary["model_sha256"]}
        write_json(output / "development_freeze.json", freeze)
    else:
        freeze = json.loads((output / "development_freeze.json").read_text(encoding="utf-8"))
        model = LinearPairProposer.load(model_path)
        if freeze["model_sha256"] != hashlib.sha256(model_path.read_bytes()).hexdigest():
            raise SystemExit("frozen model hash mismatch")
        mode, budget = freeze["proposal_mode"], freeze["pair_budget"]

    model = LinearPairProposer.load(model_path)
    retriever.relation_scorer = QueryConditionedRelationScorer(client, retriever.config.relation_threshold,
                                                                model, budget)
    pair_metrics_path = output / f"pair_metrics_{args.split}.json"
    if resume_development and pair_metrics_path.exists():
        learned_metrics = json.loads(pair_metrics_path.read_text(encoding="utf-8"))
    else:
        learned_metrics = pair_metrics(queries, gold_by_id, retriever, model, budget)
        write_json(pair_metrics_path, learned_metrics)
    learned_prefilter = "learned" if mode == "learned" else "hybrid_learned"
    warm = client.warm_cases(warm_cases(queries, retriever, learned_prefilter))
    if warm.get("failed_batch_count"):
        raise SystemExit("cache warm failed; rerun resumes")
    metrics, funnels, matrices, selector, cache, type_stats = evaluate_downstream(
        args.split, queries, gold_by_id, retriever,
        {"rule_improved": "improved", "stage3a_frozen": learned_prefilter})
    write_json(output / f"downstream_metrics_{args.split}.json", metrics)
    write_json(output / f"relation_funnel_{args.split}.json", funnels)
    write_json(output / f"relation_selection_matrix_{args.split}.json", matrices)
    write_json(output / f"selector_diagnostic_corrected_{args.split}.json", selector)
    write_json(output / f"llm_cache_diagnostics_{args.split}.json", {"warm": warm, "evaluation": cache})
    write_json(output / f"relation_type_breakdown_{args.split}.json", type_stats)
    write_json(output / "config.json", raw)
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
        "benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1", "splits": {}, "test_gold_accessed": False,
        "sealed_test_evaluator_accessed": False, "private_test_artifact_accessed": False,
        "target_method_test_runs": 0, "benchmark_issue": "BENCHMARK_ISSUE_FOUND"}
    summary["splits"][args.split] = {"pair_metrics": learned_metrics, "downstream_metrics": metrics,
        "relation_funnel": funnels, "relation_selection_matrix": matrices,
        "selector_diagnostic_corrected": selector, "relation_type_breakdown": type_stats,
        "llm_cache": {"warm": warm, "evaluation": cache}}
    write_json(summary_path, summary)
    print(json.dumps(summary["splits"][args.split], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
