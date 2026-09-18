"""Run the four frozen TEF-RAG v6 validation ablations; never reads test data."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage3a import digest, group_split
from scripts.run_tef_rag_v6_stage3b import features_for, prediction_for
from scripts.run_tef_rag_v6_stage3c import query_items
from scripts.run_tef_rag_v6_stage3d import (EXPECTED_SPLIT_HASH, fit, make_pairs,
    prepare_pairs, runtime as stage3d_runtime, select_r1_negatives)
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete
from tef_rag_v6.llm_relation import LLMRelationClient
from tef_rag_v6.nonlinear_ranknet import (NonlinearSetRanker, normalization_from_train,
    rank_items, vectorize)
from tef_rag_v6.pairwise_ranker import deterministic_subsample, select_round0_negatives
from tef_rag_v6.set_scorer import BANK_VERSION, candidate_bank

CONFIG = ROOT / "configs/tef_rag_v6_stage3d_nonlinear_ranknet.json"
OUT = ROOT / "results/v6/ablation"
CHECKPOINT = ROOT / ".cache/tef_rag_v6_ablation"
FULL_MODEL = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/model.pt"
FULL_NORM = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json"
FULL_SCHEMA = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/feature_schema.json"
FULL_METRICS = ROOT / "results/v6/stage3d_nonlinear_ranknet/ranking_metrics_validation.json"
STAGE3A_METRICS = ROOT / "results/v6/stage3a_learned_pair_proposal/downstream_metrics_validation.json"

GRAPH_FEATURES = {
    "active_edge_count", "connected_node_count", "disconnected_node_count",
    "edge_conf_max", "edge_conf_mean", "edge_conf_min", "edge_conf_sum", "edge_density",
    "hand_connectivity", "hand_disconnected_penalty", "hand_edge_sum",
    "indegree_max", "indegree_mean", "outdegree_max", "outdegree_mean",
    "largest_component_size", "length2_path_count", "longest_directed_path",
    "weak_component_count",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair_worker(shard, worker_count, mode, model_path=None, norm_path=None):
    """CPU-only/cache-only pair construction worker; no network transport is available."""
    torch.set_num_threads(1)
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    _, _, _, _, retriever, _ = stage3d_runtime(raw)
    queries, gold = load_inputs("development")
    train_groups, _ = group_split(queries, raw["seed"])
    scorer = (NonlinearSetRanker.load(Path(model_path), Path(norm_path))
              if mode == "r1" else None)
    records = []
    stats = Counter()
    for index, query in enumerate(queries, 1):
        if (index - 1) % worker_count != shard:
            continue
        _, _, items = query_items(query, gold[query["query_id"]], retriever)
        positives = deterministic_subsample([item for item in items if item["flow_complete"]], 30)
        negatives = [item for item in items if not item["flow_complete"]]
        if positives:
            selected = (select_round0_negatives(negatives, 30, 10) if scorer is None
                        else select_r1_negatives(negatives, scorer, 20, 10))
            pairs = make_pairs(positives, selected)
            records.append((index, mode == "r0" and str(query["chain_id"]) in train_groups, pairs))
            stats.update(queries_with_positive=1, ranking_pairs=len(pairs))
        else:
            stats.update(queries_without_positive=1)
    return records, dict(stats)


def parallel_pairs(mode, model_path=None, norm_path=None, worker_count=4):
    records, stats = [], Counter()
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(pair_worker, shard, worker_count, mode,
                                   str(model_path) if model_path else None,
                                   str(norm_path) if norm_path else None)
                   for shard in range(worker_count)]
        for completed, future in enumerate(as_completed(futures), 1):
            part_records, part = future.result()
            records.extend(part_records); stats.update(part)
            print(f"ablation {mode} pair shards: {completed}/{worker_count}", flush=True)
    records.sort(key=lambda value: value[0])
    full_pairs = [pair for _, _, pairs in records for pair in pairs]
    train_pairs = [pair for _, in_train, pairs in records if in_train for pair in pairs]
    return train_pairs, full_pairs, dict(stats)


def heuristic_query_items(query, gold, retriever):
    public = retriever._public_query(query)
    prediction = retriever.retrieve(query, relation_mode="llm", search_mode="greedy",
                                    prefilter_mode="improved")
    diagnostics = prediction["relation_diagnostics"]
    if (diagnostics["llm_called_pair_count"] or diagnostics["request_count"]
            or diagnostics["cache_hit_count"] != diagnostics["cache_lookup_count"]):
        raise RuntimeError("heuristic Top32 ablation requires complete frozen relation-cache coverage")
    eligible = [item for item in retriever.candidate_retrieval(public)
                if retriever.temporal_eligibility(item["document"], public)[0]]
    scores = retriever._node_scores(public, eligible)
    pool = prediction["search_diagnostics"]["search_pool_ids"]
    demands = retriever._role_demands(public["query_text"])
    raw_ids, _ = retriever._select_flow(
        [{"document": retriever.by_id[value]} for value in pool], scores,
        prediction["relation_graph"], demands, use_relations=True, use_flow=True,
        search_mode="raw_beam")
    bank = candidate_bank(pool, scores, prediction["selected_evidence_ids"], raw_ids)
    items = []
    for ids in bank:
        aware, hand = features_for(ids, public, prediction, scores, demands, retriever, True)
        items.append({"query_id": query["query_id"], "ids": ids,
            "agnostic": {key: value for key, value in aware.items() if not key.startswith("relation=")},
            "hand_score": hand["total"], "flow_complete": bool(flow_complete(list(ids), gold))})
    return public, prediction, items


def evaluate_rankers(queries, gold, retriever, rankers, item_loader=query_items):
    values = {name: [] for name in rankers}
    cache = Counter()
    for index, query in enumerate(queries, 1):
        public, prediction, items = item_loader(query, gold[query["query_id"]], retriever)
        diagnostics = prediction["relation_diagnostics"]
        cache.update(lookups=diagnostics["cache_lookup_count"], hits=diagnostics["cache_hit_count"])
        base = {**prediction, "query_text": public["query_text"]}
        for name, scorer in rankers.items():
            ids = (rank_items(items, scorer)[0]["ids"] if items
                   else tuple(prediction["selected_evidence_ids"]))
            values[name].append(evaluate_prediction(prediction_for(ids, base, retriever),
                                                     gold[query["query_id"]], 5))
        if index % 20 == 0:
            print(f"ablation validation: {index}/{len(queries)}", flush=True)
    if cache["lookups"] != cache["hits"]:
        raise RuntimeError("validation relation cache was not complete")
    return {name: average(rows) for name, rows in values.items()}, dict(cache)


def evaluation_worker(shard, worker_count, mode):
    torch.set_num_threads(1)
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    _, _, _, client, retriever, _ = stage3d_runtime(raw)
    queries, gold = load_inputs("validation")
    queries = [query for index, query in enumerate(queries) if index % worker_count == shard]
    if mode == "learned":
        rankers = {
            "without_relation_graph_features": NonlinearSetRanker.load(
                CHECKPOINT / "without_relation_graph_features.pt",
                CHECKPOINT / "without_relation_graph_features_normalization.json"),
            "without_hard_negative_mining": NonlinearSetRanker.load(
                CHECKPOINT / "without_hard_negative_mining.pt",
                CHECKPOINT / "without_hard_negative_mining_normalization.json"),
        }
        loader = query_items
    else:
        client.config = replace(client.config, max_pairs_per_query=32)
        retriever.relation_scorer.config = client.config
        rankers = {"without_learned_pair_proposal": NonlinearSetRanker.load(FULL_MODEL, FULL_NORM)}
        loader = heuristic_query_items
    return evaluate_rankers(queries, gold, retriever, rankers, loader)


def parallel_evaluate(mode, worker_count=4):
    values, cache = {}, Counter()
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(evaluation_worker, shard, worker_count, mode)
                   for shard in range(worker_count)]
        for completed, future in enumerate(as_completed(futures), 1):
            part, part_cache = future.result()
            for name, metrics in part.items():
                values.setdefault(name, []).append(metrics)
            cache.update(part_cache)
            print(f"ablation {mode} validation shards: {completed}/{worker_count}", flush=True)
    # Every shard has the same 120-query cardinality, so the mean of shard means is exact.
    return ({name: {key: sum(row[key] for row in rows) / len(rows)
                    for key in rows[0]} for name, rows in values.items()}, dict(cache))


def train_ablation_models(raw, retriever, schema):
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    r0_path = CHECKPOINT / "without_hard_negative_mining.pt"
    r0_norm_path = CHECKPOINT / "without_hard_negative_mining_normalization.json"
    graph_path = CHECKPOINT / "without_relation_graph_features.pt"
    graph_norm_path = CHECKPOINT / "without_relation_graph_features_normalization.json"
    stats_path = CHECKPOINT / "training_stats.json"
    if all(path.exists() for path in (r0_path, r0_norm_path, graph_path, graph_norm_path, stats_path)):
        return (NonlinearSetRanker.load(r0_path, r0_norm_path),
                NonlinearSetRanker.load(graph_path, graph_norm_path),
                json.loads(stats_path.read_text(encoding="utf-8")),
                (r0_path, r0_norm_path, graph_path, graph_norm_path))

    development, _ = load_inputs("development")
    train_groups, tune_groups = group_split(development, raw["seed"])
    split_hash = digest({"train": sorted(train_groups), "tune": sorted(tune_groups)})
    if split_hash != EXPECTED_SPLIT_HASH:
        raise RuntimeError("grouped split mismatch")
    train_pairs, full_pairs, r0_stats = parallel_pairs("r0")
    full_features = schema["agnostic_features"]
    reduced_features = [name for name in full_features if name not in GRAPH_FEATURES]
    if len(full_features) != 62 or len(reduced_features) != 43:
        raise RuntimeError("unexpected full/reduced feature dimensions")

    frozen_norm = json.loads(FULL_NORM.read_text(encoding="utf-8"))
    full_mean = np.asarray(frozen_norm["mean"], dtype=np.float32)
    full_std = np.asarray(frozen_norm["std"], dtype=np.float32)
    r0 = fit(full_pairs, full_features, full_mean, full_std, raw, "round0", "all_development_ablation")
    r0.save(r0_path)
    write_json(r0_norm_path, {"feature_names": full_features, "mean": full_mean.tolist(),
                              "std": full_std.tolist(), "source": "frozen_stage3d_train_groups"})

    reduced_train = vectorize([row for pair in train_pairs for row in pair], reduced_features)
    reduced_mean, reduced_std = normalization_from_train(reduced_train)
    graph_r0 = fit(full_pairs, reduced_features, reduced_mean, reduced_std, raw,
                   "round0", "all_development_no_graph_features")
    graph_r0_path = CHECKPOINT / "without_relation_graph_features_r0.pt"
    graph_r0_norm_path = CHECKPOINT / "without_relation_graph_features_r0_normalization.json"
    graph_r0.save(graph_r0_path)
    write_json(graph_r0_norm_path, {"feature_names": reduced_features, "mean": reduced_mean.tolist(),
                                    "std": reduced_std.tolist()})
    all_groups = train_groups | tune_groups
    _, r1_pairs, r1_stats = parallel_pairs("r1", graph_r0_path, graph_r0_norm_path)
    graph_r1 = fit(r1_pairs, reduced_features, reduced_mean, reduced_std, raw,
                   "round1", "all_development_no_graph_features")
    graph_r1.save(graph_path)
    write_json(graph_norm_path, {"feature_names": reduced_features, "mean": reduced_mean.tolist(),
        "std": reduced_std.tolist(), "source": "development_train_groups_only",
        "excluded_graph_features": sorted(GRAPH_FEATURES)})
    stats = {"seed": raw["seed"], "group_split_hash": split_hash,
        "train_groups": len(train_groups), "tune_groups": len(tune_groups),
        "round0": r0_stats, "graphless_round1": r1_stats,
        "full_feature_count": len(full_features), "graphless_feature_count": len(reduced_features),
        "hard_negative_rounds": 1, "hyperparameter_sweep": False}
    write_json(stats_path, stats)
    return r0, graph_r1, stats, (r0_path, r0_norm_path, graph_path, graph_norm_path)


def warm_heuristic_cache():
    """Serially fill only missing validation heuristic-Top32 judgments."""
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    _, _, _, frozen_client, retriever, _ = stage3d_runtime(raw)
    config = replace(frozen_client.config, max_pairs_per_query=32,
                     request_interval_seconds=4.0, case_batch_mode=True)
    client = LLMRelationClient(config, frozen_client.taxonomy)
    retriever.relation_scorer.client = client
    retriever.relation_scorer.config = config
    queries, _ = load_inputs("validation")
    cases = []
    for index, query in enumerate(queries):
        public = retriever._public_query(query)
        eligible = [item for item in retriever.candidate_retrieval(public)
                    if retriever.temporal_eligibility(item["document"], public)[0]]
        scores = retriever._node_scores(public, eligible)
        pool = sorted(eligible, key=lambda item: (-scores[item["document"]["evidence_id"]]["total"],
                                                   item["document"]["evidence_id"]))[:30]
        pairs, _ = retriever.relation_scorer.prefilter(
            pool, scores, retriever._relation_kind, retriever._similarity, "improved", query=public)
        cases.append({"case_id": f"ablation-v-{index:04d}", "query": public, "pairs": pairs})
    stats = client.warm_cases(cases)
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    write_json(CHECKPOINT / "heuristic_top32_cache_warm.json", stats)
    if stats["failed_batch_count"] or stats["padded_missing_count"]:
        raise RuntimeError("heuristic cache warm incomplete; rerun resumes from successful judgments")
    print(json.dumps(stats, indent=2))


def main():
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    stage3c, stage3c_freeze, stage3a_freeze, client, retriever, schema = stage3d_runtime(raw)
    if BANK_VERSION != "stage3b-full5-top15-swap-v1":
        raise RuntimeError("candidate bank version mismatch")
    full = json.loads(FULL_METRICS.read_text(encoding="utf-8"))["frozen_mlp"]
    stage3a = json.loads(STAGE3A_METRICS.read_text(encoding="utf-8"))["stage3a_frozen"]
    expected = {"recall_at_5": 0.7566666666666666, "ndcg_at_5": 0.6885479556270926,
        "complete_at_5": 0.40625, "flow_complete_at_5": 0.4041666666666667,
        "edge_recall": 0.47638888888888886}
    if any(abs(full[key] - value) > 1e-12 for key, value in expected.items()):
        raise RuntimeError("full validation reference mismatch")
    if not (stage3a_freeze["pair_budget"] == 32 and retriever.config.search_pool_k == 30
            and stage3a_freeze["relation_prompt_version"] == "tef-v6-stage2a-relation-v7"):
        raise RuntimeError("Stage3A comparison is not semantically comparable")

    r0, graphless, training, paths = train_ablation_models(raw, retriever, schema)
    validation, _ = load_inputs("validation")
    learned_metrics, learned_cache = parallel_evaluate("learned")
    heuristic_metrics, heuristic_cache = parallel_evaluate("heuristic")

    metrics = {"full_tef_rag": full, **heuristic_metrics, **learned_metrics,
               "without_nonlinear_set_ranker": stage3a}
    deltas = {name: {"flow_complete_at_5": value["flow_complete_at_5"] - full["flow_complete_at_5"],
                     "recall_at_5": value["recall_at_5"] - full["recall_at_5"]}
              for name, value in metrics.items() if name != "full_tef_rag"}
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "metrics.json", {"metrics": metrics, "delta_vs_full": deltas})
    manifest = {"base_commit": "8404d3d40d63afc89e67f7e39a1e26945464f125",
        "split": "validation", "query_count": len(validation), "seed": raw["seed"],
        "pair_budget": 32, "search_pool_k": 30, "candidate_bank_version": BANK_VERSION,
        "relation_prompt_version": stage3a_freeze["relation_prompt_version"],
        "relation_threshold": 0.6, "stage3a_result_reused": True,
        "stage3a_semantically_comparable": True, "training": training,
        "model_hashes": {"without_hard_negative_mining": sha256(paths[0]),
                         "without_relation_graph_features": sha256(paths[2])},
        "normalization_hashes": {"without_hard_negative_mining": sha256(paths[1]),
                                 "without_relation_graph_features": sha256(paths[3])},
        "validation_cache": {"learned": learned_cache, "heuristic_top32": heuristic_cache,
            "heuristic_warm": json.loads((CHECKPOINT / "heuristic_top32_cache_warm.json").read_text(encoding="utf-8"))},
        "new_hyperparameter_sweep": False, "sealed_test_accessed": False,
        "test_gold_accessed": False, "test_predictions_run": False}
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"metrics": metrics, "delta_vs_full": deltas}, indent=2))


if __name__ == "__main__":
    if "--warm-heuristic-cache" in sys.argv:
        warm_heuristic_cache()
    else:
        main()
