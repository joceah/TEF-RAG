"""Train and evaluate Stage 3C same-query pairwise set rankers, cache-only."""
from __future__ import annotations

import argparse, hashlib, json, platform, statistics, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage3a import digest, group_split
from scripts.run_tef_rag_v6_stage3b import (context, features_for, prediction_for,
                                            runtime as stage3b_runtime)
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete
from tef_rag_v6.pairwise_ranker import (LinearPairwiseSetRanker, construct_pairs,
    deterministic_subsample, mirrored_examples, rank_items, select_mined_negatives,
    select_round0_negatives)
from tef_rag_v6.set_scorer import BANK_VERSION, LinearSetScorer

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage3c_pairwise_set_ranker.json"
EXPECTED_SPLIT_HASH = "5eaff9f55889dcb07386f24b7da6684e658330010768bed73ada7a0c69e15811"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def forbidden_http(*args, **kwargs):
    raise RuntimeError("Stage3C cache miss: HTTP is forbidden")


def runtime(raw):
    stage3b = json.loads((ROOT / raw["stage3b_config"]).read_text(encoding="utf-8"))
    stage3a, freeze, client, retriever = stage3b_runtime(stage3b)
    client.transport = forbidden_http
    proposer_path = ROOT / stage3a["artifact_dir"] / "model.json"
    checks = {
        "base_stage3a_commit": stage3b["base_stage3a_commit"],
        "candidate_bank_version": BANK_VERSION,
        "candidate_bank_top_m": stage3b["candidate_bank_top_m"],
        "stage3a_proposer_model_hash": sha256(proposer_path),
        "stage3a_pair_budget": retriever.relation_scorer.pair_budget,
        "search_pool_k": retriever.config.search_pool_k,
        "relation_prompt_version": freeze["relation_prompt_version"],
    }
    expected = {
        "base_stage3a_commit": raw["base_stage3a_commit"],
        "candidate_bank_version": raw["candidate_bank_version"],
        "candidate_bank_top_m": raw["candidate_bank_top_m"],
        "stage3a_proposer_model_hash": freeze["model_sha256"],
        "stage3a_pair_budget": 32,
        "search_pool_k": 30,
        "relation_prompt_version": "tef-v6-stage2a-relation-v7",
    }
    for key, value in expected.items():
        if checks[key] != value:
            raise RuntimeError(f"frozen runtime mismatch: {key}: {checks[key]!r} != {value!r}")
    return stage3b, stage3a, freeze, client, retriever


def query_items(query, gold, retriever):
    public, prediction, scores, demands, bank = context(query, retriever)
    items = []
    for ids in bank:
        aware, hand = features_for(ids, public, prediction, scores, demands, retriever, True)
        items.append({"query_id": query["query_id"], "ids": ids, "aware": aware,
            "agnostic": {key: value for key, value in aware.items() if not key.startswith("relation=")},
            "hand_score": hand["total"], "hardness": hand["total"],
            "flow_complete": bool(flow_complete(list(ids), gold))})
    return public, prediction, items


def prepare_pairs(queries, gold_by_id, retriever, groups, raw, round0_rankers=None):
    all_pairs = {"agnostic": [], "aware": []}
    stats = Counter(); bank_sizes = []; started = time.perf_counter()
    for index, query in enumerate(queries, 1):
        if str(query["chain_id"]) not in groups:
            continue
        _, _, items = query_items(query, gold_by_id[query["query_id"]], retriever)
        positives = deterministic_subsample([item for item in items if item["flow_complete"]],
                                            raw["max_positive_sets"])
        negatives = [item for item in items if not item["flow_complete"]]
        bank_sizes.append(len(items)); stats["queries"] += 1
        if not positives:
            stats["queries_without_positive_bank_set"] += 1
            continue
        stats["queries_with_positive_bank_set"] += 1
        for kind in ("agnostic", "aware"):
            if round0_rankers is None:
                selected = select_round0_negatives(negatives, raw["round0_hard_negatives"],
                                                   raw["round0_diverse_negatives"])
            else:
                selected = select_mined_negatives(negatives, round0_rankers[kind], kind == "aware",
                    raw["round1_model_hard_negatives"], raw["round1_handcrafted_hard_negatives"])
            for item in selected:
                item["hardness"] = (round0_rankers[kind].utility(item[kind])
                                    if round0_rankers else item["hand_score"])
            pairs = construct_pairs(query["query_id"], positives, selected, kind,
                raw["max_negatives_per_positive"], raw["max_pairs_per_query"])
            all_pairs[kind].extend(pairs)
            stats[f"{kind}_pairs"] += len(pairs)
        if index % 80 == 0:
            print(f"pair construction: {index}/{len(queries)}", flush=True)
    stats["candidate_sets"] = sum(bank_sizes)
    stats["mean_sets_per_query"] = statistics.mean(bank_sizes) if bank_sizes else 0
    stats["runtime_seconds"] = time.perf_counter() - started
    return all_pairs, dict(stats)


def fit(pairs, kind, raw, round_name, group_scope):
    rows, labels = mirrored_examples(pairs[kind])
    if not rows:
        raise RuntimeError(f"no {kind} ranking pairs")
    vectorizer = DictVectorizer(sparse=True, sort=True)
    matrix = vectorizer.fit_transform(rows)
    parameters = dict(raw["model_hyperparameters"])
    classifier = LogisticRegression(random_state=raw["seed"], **parameters).fit(matrix, np.asarray(labels))
    intercept = float(np.asarray(classifier.intercept_).reshape(-1)[0])
    if intercept != 0.0:
        raise RuntimeError("pairwise model unexpectedly learned an intercept")
    metadata = {"objective": "same_query_pairwise_logistic", "round": round_name,
        "type_aware": kind == "aware", "bank_version": BANK_VERSION, "seed": raw["seed"],
        "group_scope": group_scope, "pair_count": len(pairs[kind]), "mirrored_example_count": len(rows)}
    return LinearPairwiseSetRanker(vectorizer.feature_names_, classifier.coef_[0].tolist(), metadata)


def positive_rank_metrics(ranks, query_count, fallback_positive_count=0):
    available = [rank for rank in ranks if rank is not None]
    output = {f"positive_set_hit_at_{cutoff}": (fallback_positive_count + sum(rank is not None and rank <= cutoff for rank in ranks)) / query_count
              for cutoff in (1, 3, 5, 10)}
    output.update(bank_oracle_queries=len(available), bank_oracle_fraction=len(available) / query_count)
    if available:
        values = np.asarray(available, dtype=float)
        output.update(mean_best_positive_rank=float(np.mean(values)), median_best_positive_rank=float(np.median(values)),
                      p75_best_positive_rank=float(np.percentile(values, 75)),
                      p90_best_positive_rank=float(np.percentile(values, 90)),
                      fraction_rank_1=float(np.mean(values == 1)), fraction_rank_le_3=float(np.mean(values <= 3)),
                      fraction_rank_le_5=float(np.mean(values <= 5)), fraction_rank_le_10=float(np.mean(values <= 10)))
    return output


def evaluate(queries, gold_by_id, retriever, rankers, pointwise, methods=None):
    methods = methods or list(rankers)
    names = ["stage3a_greedy", "bank_handcrafted", "stage3b_pointwise_type_aware"] + methods
    rows = {name: [] for name in names}; ranks = {name: [] for name in methods}
    correct = Counter(); total = Counter(); fallback_positive = Counter(); bank_sizes = []; oracle = 0; cache = Counter()
    for index, query in enumerate(queries, 1):
        public, prediction, items = query_items(query, gold_by_id[query["query_id"]], retriever)
        diagnostics = prediction["relation_diagnostics"]
        cache.update(lookups=diagnostics["cache_lookup_count"], hits=diagnostics["cache_hit_count"])
        bank_sizes.append(len(items)); oracle += any(item["flow_complete"] for item in items)
        base = {**prediction, "query_text": public["query_text"]}
        if not items:
            fallback = tuple(prediction["selected_evidence_ids"])
            result = evaluate_prediction(prediction_for(fallback, base, retriever),
                                         gold_by_id[query["query_id"]], 5)
            for name in names:
                rows[name].append(result)
            for name in methods:
                ranks[name].append(None)
                fallback_positive[name] += int(flow_complete(list(fallback), gold_by_id[query["query_id"]]))
            continue
        hand_ranked = sorted(items, key=lambda item: (-item["hand_score"], item["ids"]))
        point_ranked = sorted(items, key=lambda item: (-pointwise.score(item["aware"]), item["ids"]))
        choices = {"stage3a_greedy": tuple(prediction["selected_evidence_ids"]),
                   "bank_handcrafted": hand_ranked[0]["ids"],
                   "stage3b_pointwise_type_aware": point_ranked[0]["ids"]}
        for name in methods:
            kind = "aware" if "aware" in name else "agnostic"
            ranked = rank_items(items, rankers[name], kind)
            choices[name] = ranked[0]["ids"]
            positive_rank = next((position for position, item in enumerate(ranked, 1) if item["flow_complete"]), None)
            ranks[name].append(positive_rank)
            positives = deterministic_subsample([item for item in items if item["flow_complete"]], 30)
            negatives = select_round0_negatives([item for item in items if not item["flow_complete"]], 30, 0)
            if not negatives:
                continue
            for positive_index, positive in enumerate(positives):
                ordered_negatives = negatives[positive_index % len(negatives):] + negatives[:positive_index % len(negatives)]
                for negative in ordered_negatives[:5]:
                    total[name] += 1
                    correct[name] += rankers[name].utility(positive[kind]) > rankers[name].utility(negative[kind])
        for name, ids in choices.items():
            rows[name].append(evaluate_prediction(prediction_for(ids, base, retriever),
                                                  gold_by_id[query["query_id"]], 5))
        if index % 20 == 0 or index == len(queries):
            print(f"ranking evaluation: {index}/{len(queries)}", flush=True)
    bank = {"candidate_bank_version": BANK_VERSION, "query_count": len(queries),
        "mean_sets_per_query": statistics.mean(bank_sizes), "median_sets_per_query": statistics.median(bank_sizes),
        "max_sets_per_query": max(bank_sizes), "flow_complete_oracle_count": oracle,
        "flow_complete_oracle": oracle / len(queries), "same_bank_as_stage3b": True}
    return ({name: average(value) for name, value in rows.items()}, bank,
            {"relation_cache_lookups": cache["lookups"], "cache_hits": cache["hits"],
             "cache_hit_rate": cache["hits"] / cache["lookups"], "new_llm_calls": 0, "new_http_requests": 0},
            {name: positive_rank_metrics(value, len(queries), fallback_positive[name]) for name, value in ranks.items()},
            {name: {"correct_pairs": correct[name], "evaluation_pairs": total[name],
                    "pairwise_accuracy": correct[name] / total[name] if total[name] else None}
             for name in methods})


def verify_freeze(freeze, current, only_paths=False):
    for key, value in current.items():
        actual = sha256(value) if isinstance(value, Path) else value
        if freeze.get(key) != actual:
            raise RuntimeError(f"freeze mismatch: {key}: {actual!r} != {freeze.get(key)!r}")
    if only_paths:
        return True
    required = ("base_stage3b_commit", "base_stage3a_commit", "candidate_bank_version",
        "candidate_bank_top_m", "feature_schema_hash", "stage3a_proposer_model_hash",
        "stage3a_pair_budget", "search_pool_k", "relation_prompt_version", "agnostic_model_hash",
        "aware_model_hash", "selected_ranker_model_hash", "group_split_hash", "seed")
    missing = [key for key in required if key not in freeze]
    if missing:
        raise RuntimeError(f"incomplete freeze: {missing}")
    return True


def save_models(artifact, models):
    paths = {}
    for name, model in models.items():
        path = artifact / f"{name}.json"; model.save(path); paths[name] = path
    return paths


def historical_stage3b_tune():
    data = json.loads((ROOT / "results/v6/stage3b_learned_set_scorer/training_summary.json").read_text(encoding="utf-8"))
    return data["tune_metrics"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--split", choices=("development", "validation"), default="development")
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    stage3b, stage3a, stage3a_freeze, client, retriever = runtime(raw)
    output, artifact = ROOT / raw["output_dir"], ROOT / raw["artifact_dir"]
    queries, gold = load_inputs(args.split)
    freeze_path = output / "development_freeze.json"
    if args.split == "development":
        train_groups, tune_groups = group_split(queries, raw["seed"])
        split_hash = digest({"train": sorted(train_groups), "tune": sorted(tune_groups)})
        if split_hash != EXPECTED_SPLIT_HASH or (len(train_groups), len(tune_groups)) != (188, 52):
            raise RuntimeError("development grouped split mismatch")
        r0_pairs, r0_stats = prepare_pairs(queries, gold, retriever, train_groups, raw)
        r0 = {kind: fit(r0_pairs, kind, raw, "round0", "development_train") for kind in ("agnostic", "aware")}
        r1_pairs, r1_stats = prepare_pairs(queries, gold, retriever, train_groups, raw, r0)
        r1 = {kind: fit(r1_pairs, kind, raw, "round1", "development_train") for kind in ("agnostic", "aware")}
        tune_queries = [query for query in queries if str(query["chain_id"]) in tune_groups]
        tune_rankers = {"pairwise_agnostic_r0": r0["agnostic"], "pairwise_aware_r0": r0["aware"],
                        "pairwise_agnostic_r1": r1["agnostic"], "pairwise_aware_r1": r1["aware"]}
        pointwise = LinearSetScorer.load(ROOT / stage3b["artifact_dir"] / "type_aware_model.json")
        tune_metrics, tune_bank, tune_cache, tune_ranks, tune_accuracy = evaluate(
            tune_queries, gold, retriever, tune_rankers, pointwise)
        historical = historical_stage3b_tune()
        tune_metrics["stage3a_greedy"] = historical["stage3a_greedy"]
        tune_metrics["bank_handcrafted"] = historical["bank_handcrafted"]
        tune_metrics["stage3b_pointwise_type_aware"] = historical["learned_type_aware"]
        candidates = list(tune_rankers)
        selected = max(candidates, key=lambda name: (tune_metrics[name]["flow_complete_at_5"],
            tune_metrics[name]["complete_at_5"], tune_metrics[name]["recall_at_5"], tune_metrics[name]["ndcg_at_5"], name))
        all_groups = train_groups | tune_groups
        full_r0_pairs, full_r0_stats = prepare_pairs(queries, gold, retriever, all_groups, raw)
        full_r0 = {kind: fit(full_r0_pairs, kind, raw, "round0", "all_development") for kind in ("agnostic", "aware")}
        full_r1_pairs, full_r1_stats = prepare_pairs(queries, gold, retriever, all_groups, raw, full_r0)
        full_r1 = {kind: fit(full_r1_pairs, kind, raw, "round1", "all_development") for kind in ("agnostic", "aware")}
        paths = save_models(artifact, {"round0_type_agnostic": full_r0["agnostic"],
            "round0_type_aware": full_r0["aware"], "final_type_agnostic": full_r1["agnostic"],
            "final_type_aware": full_r1["aware"]})
        selected_round = "round0" if selected.endswith("r0") else "final"
        selected_kind = "type_aware" if "aware" in selected else "type_agnostic"
        selected_path = paths[f"{selected_round}_{selected_kind}"]
        schema = {"candidate_bank_version": BANK_VERSION,
            "agnostic_features": full_r1["agnostic"].feature_names,
            "aware_features": full_r1["aware"].feature_names,
            "relation_type_prefix": "relation=", "forbidden": ["gold", "required_groups", "required_flow_edges",
                "query_id", "chain_id", "split", "difficulty"]}
        write_json(artifact / "feature_schema.json", schema)
        training_metadata = {"python_version": platform.python_version(), "sklearn_version": sklearn.__version__,
            "seed": raw["seed"], "train_groups": len(train_groups), "tune_groups": len(tune_groups),
            "group_split_hash": split_hash, "round0_train": r0_stats, "round1_train": r1_stats,
            "round0_full_development": full_r0_stats, "round1_full_development": full_r1_stats,
            "selected_frozen_ranker": selected, "hard_negative_rounds": 1,
            "model_sha256": {path.name: sha256(path) for path in paths.values()}}
        write_json(artifact / "training_metadata.json", training_metadata)
        write_json(output / "training_summary.json", training_metadata)
        write_json(output / "ranking_metrics_development.json", tune_metrics)
        write_json(output / "ranking_ablation_development.json", tune_metrics)
        write_json(output / "positive_rank_diagnostics_development.json", tune_ranks)
        write_json(output / "pairwise_accuracy_development.json", tune_accuracy)
        full_bank = json.loads((ROOT / stage3b["output_dir"] / "candidate_bank_development.json").read_text(encoding="utf-8"))
        full_bank.update(candidate_bank_version=BANK_VERSION, same_bank_as_stage3b=True)
        stage3b_cache = json.loads((ROOT / stage3b["output_dir"] / "cache_diagnostics_development.json").read_text(encoding="utf-8"))
        full_cache = {"relation_cache_lookups": stage3b_cache["lookups"], "cache_hits": stage3b_cache["hits"],
                      "cache_hit_rate": stage3b_cache["hit_rate"], "new_llm_calls": 0, "new_http_requests": 0}
        write_json(output / "candidate_bank_development.json", full_bank)
        write_json(output / "cache_diagnostics_development.json", full_cache)
        hard_effect = {kind: {"round0_flow_complete": tune_metrics[f"pairwise_{kind}_r0"]["flow_complete_at_5"],
            "round1_flow_complete": tune_metrics[f"pairwise_{kind}_r1"]["flow_complete_at_5"],
            "round0_positive_set_hit_at_3": tune_ranks[f"pairwise_{kind}_r0"]["positive_set_hit_at_3"],
            "round1_positive_set_hit_at_3": tune_ranks[f"pairwise_{kind}_r1"]["positive_set_hit_at_3"],
            "round0_positive_set_hit_at_5": tune_ranks[f"pairwise_{kind}_r0"]["positive_set_hit_at_5"],
            "round1_positive_set_hit_at_5": tune_ranks[f"pairwise_{kind}_r1"]["positive_set_hit_at_5"],
            "round0_median_best_positive_rank": tune_ranks[f"pairwise_{kind}_r0"].get("median_best_positive_rank"),
            "round1_median_best_positive_rank": tune_ranks[f"pairwise_{kind}_r1"].get("median_best_positive_rank"),
            "round0_pairwise_accuracy": tune_accuracy[f"pairwise_{kind}_r0"]["pairwise_accuracy"],
            "round1_pairwise_accuracy": tune_accuracy[f"pairwise_{kind}_r1"]["pairwise_accuracy"]}
            for kind in ("agnostic", "aware")}
        write_json(output / "hard_negative_mining_development.json", hard_effect)
        freeze = {"status": "FROZEN_AFTER_DEVELOPMENT", "base_stage3b_commit": raw["base_stage3b_commit"],
            "base_stage3a_commit": raw["base_stage3a_commit"], "candidate_bank_version": BANK_VERSION,
            "candidate_bank_top_m": raw["candidate_bank_top_m"], "feature_schema_hash": digest(schema),
            "stage3a_proposer_model_hash": stage3a_freeze["model_sha256"], "stage3a_pair_budget": 32,
            "search_pool_k": 30, "relation_prompt_version": stage3a_freeze["relation_prompt_version"],
            "agnostic_model_hash": sha256(paths[f"{selected_round}_type_agnostic"]),
            "aware_model_hash": sha256(paths[f"{selected_round}_type_aware"]),
            "selected_ranker": selected, "selected_ranker_model_hash": sha256(selected_path),
            "group_split_hash": split_hash, "seed": raw["seed"], "validation_configuration_frozen": True}
        write_json(freeze_path, freeze)
        write_json(output / "config.json", raw)
        print(json.dumps({"selected": selected, "tune_metrics": tune_metrics}, ensure_ascii=False, indent=2))
        return

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    selected_round = "round0" if freeze["selected_ranker"].endswith("r0") else "final"
    ag_path, aw_path = artifact / f"{selected_round}_type_agnostic.json", artifact / f"{selected_round}_type_aware.json"
    selected_path = aw_path if "aware" in freeze["selected_ranker"] else ag_path
    schema = json.loads((artifact / "feature_schema.json").read_text(encoding="utf-8"))
    current = {"base_stage3b_commit": raw["base_stage3b_commit"], "base_stage3a_commit": raw["base_stage3a_commit"],
        "candidate_bank_version": BANK_VERSION, "candidate_bank_top_m": raw["candidate_bank_top_m"],
        "feature_schema_hash": digest(schema), "stage3a_proposer_model_hash": stage3a_freeze["model_sha256"],
        "stage3a_pair_budget": retriever.relation_scorer.pair_budget, "search_pool_k": retriever.config.search_pool_k,
        "relation_prompt_version": stage3a_freeze["relation_prompt_version"], "agnostic_model_hash": sha256(ag_path),
        "aware_model_hash": sha256(aw_path), "selected_ranker_model_hash": sha256(selected_path),
        "group_split_hash": EXPECTED_SPLIT_HASH, "seed": raw["seed"]}
    verify_freeze(freeze, current)
    rankers = {"frozen_pairwise_agnostic": LinearPairwiseSetRanker.load(ag_path),
               "frozen_pairwise_aware": LinearPairwiseSetRanker.load(aw_path)}
    pointwise = LinearSetScorer.load(ROOT / stage3b["artifact_dir"] / "type_aware_model.json")
    metrics, bank, cache, ranks, accuracy = evaluate(queries, gold, retriever, rankers, pointwise)
    write_json(output / "ranking_metrics_validation.json", metrics)
    write_json(output / "ranking_ablation_validation.json", metrics)
    write_json(output / "positive_rank_diagnostics_validation.json", ranks)
    write_json(output / "pairwise_accuracy_validation.json", accuracy)
    write_json(output / "candidate_bank_validation.json", bank)
    write_json(output / "cache_diagnostics_validation.json", cache)
    summary = {"benchmark": "TEF_RAG_v6_temporal_hard_benchmark_v1", "development_selection": freeze["selected_ranker"],
        "development": {"metrics": json.loads((output / "ranking_metrics_development.json").read_text(encoding="utf-8")),
                        "candidate_bank": json.loads((output / "candidate_bank_development.json").read_text(encoding="utf-8")),
                        "hard_negative_mining": json.loads((output / "hard_negative_mining_development.json").read_text(encoding="utf-8"))},
        "validation": {"metrics": metrics, "candidate_bank": bank, "positive_rank_diagnostics": ranks,
                       "pairwise_accuracy": accuracy, "cache": cache},
        "benchmark_issue": "BENCHMARK_ISSUE_FOUND", "test_gold_accessed": False,
        "sealed_test_evaluator_accessed": False, "private_test_artifact_accessed": False,
        "target_method_test_runs": 0, "validation_configuration_frozen_after_development": True,
        "new_llm_calls": 0, "new_http_requests": 0}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
