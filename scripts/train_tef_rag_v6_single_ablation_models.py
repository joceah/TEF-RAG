"""Restore frozen single-ablation RankNet models using development data only."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts.run_tef_rag_v6_joint_ablation import (LEGACY_CACHE, PUBLIC,
    read_json, runtime, sha256, write_json)
from scripts.run_tef_rag_v6_stage3a import group_split
from scripts.run_tef_rag_v6_stage3d import evaluate, fit, prepare_pairs
from tef_rag_v6 import QueryConditionedRelationScorer, load_jsonl
from tef_rag_v6.nonlinear_ranknet import NonlinearSetRanker
from tef_rag_v6.pair_proposal import LinearPairProposer

OUT = ROOT / "results/v6/single_ablation_tests"
ARTIFACT = ROOT / "artifacts/v6/single_ablation_tests"
FULL_NORM = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json"
RAW = read_json(ROOT / "configs/tef_rag_v6_stage3d_nonlinear_ranknet.json")

# These values in set_features() are functions of the relation graph. The
# graph and relation judging remain active for candidate construction.
GRAPH_FEATURES = frozenset({
    "active_edge_count", "connected_node_count", "disconnected_node_count",
    "edge_conf_max", "edge_conf_mean", "edge_conf_min", "edge_conf_sum", "edge_density",
    "hand_connectivity", "hand_disconnected_penalty", "hand_edge_sum",
    "indegree_max", "indegree_mean", "outdegree_max", "outdegree_mean",
    "largest_component_size", "length2_path_count", "longest_directed_path",
    "weak_component_count",
})
PAPER_VALIDATION = {
    "round0": ("0.6748", "0.6042", "0.2875", "0.2833"),
    "graph_free": ("0.7184", "0.6601", "0.3750", "0.3667"),
}
PAPER_METRICS = ("recall_at_5", "ndcg_at_5", "complete_at_5", "flow_complete_at_5")


def development_runtime():
    client, retriever, _, _ = runtime(LEGACY_CACHE)
    # Original development relation cache was fingerprinted with these frozen
    # settings. They differ from the released sealed-test model identity.
    client.config = replace(client.config, model="deepseek-v4-flash", thinking="disabled")
    client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("development training must be cache-only"))
    proposer = LinearPairProposer.load(ROOT / "artifacts/v6/stage3a_pair_proposer/model.json")
    retriever.relation_scorer = QueryConditionedRelationScorer(
        client, retriever.config.relation_threshold, proposer, 32)
    return client, retriever


def split_data(split):
    queries = load_jsonl(PUBLIC / f"queries_{split}.jsonl")
    gold = {row["query_id"]: row for row in load_jsonl(PUBLIC / f"gold_{split}.jsonl")}
    expected = 1440 if split == "development" else 480
    if len(queries) != expected or set(gold) != {q["query_id"] for q in queries}:
        raise RuntimeError(f"{split} data mismatch")
    return queries, gold


def save_model(name, scorer, norm):
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACT / f"{name}.pt"
    norm_path = ARTIFACT / f"{name}_normalization.json"
    scorer.save(model_path)
    write_json(norm_path, norm)
    return {"model_sha256": sha256(model_path), "normalization_sha256": sha256(norm_path),
            "model_metadata": scorer.metadata}


def train():
    if (ARTIFACT / "round0.pt").exists() or (ARTIFACT / "graph_free.pt").exists():
        raise RuntimeError("ablation models already exist; refusing to overwrite")
    queries, gold = split_data("development")
    client, retriever = development_runtime()
    train_groups, tune_groups = group_split(queries, RAW["seed"])
    if len(train_groups) != 188 or len(tune_groups) != 52:
        raise RuntimeError("frozen development group split mismatch")
    norm = read_json(FULL_NORM)
    features = norm["feature_names"]
    removed = [name for name in features if name in GRAPH_FEATURES]
    if set(removed) != GRAPH_FEATURES:
        raise RuntimeError("graph feature list differs from frozen feature schema")
    keep = [index for index, name in enumerate(features) if name not in GRAPH_FEATURES]
    graph_norm = {"feature_names": [features[i] for i in keep],
                  "mean": [norm["mean"][i] for i in keep],
                  "std": [norm["std"][i] for i in keep],
                  "source": "development_train_groups_only; subset of frozen full normalization"}
    full_groups = train_groups | tune_groups
    pairs, round0_stats = prepare_pairs(queries, gold, retriever, full_groups)
    no_hard = fit(pairs, features, np.asarray(norm["mean"], dtype=np.float32),
                  np.asarray(norm["std"], dtype=np.float32), RAW, "round0", "all_development")
    no_hard_artifact = save_model("round0", no_hard, norm)
    graph_round0 = fit(pairs, graph_norm["feature_names"],
                       np.asarray(graph_norm["mean"], dtype=np.float32),
                       np.asarray(graph_norm["std"], dtype=np.float32), RAW, "round0", "all_development")
    graph_pairs, round1_stats = prepare_pairs(queries, gold, retriever, full_groups, graph_round0)
    graph_final = fit(graph_pairs, graph_norm["feature_names"],
                      np.asarray(graph_norm["mean"], dtype=np.float32),
                      np.asarray(graph_norm["std"], dtype=np.float32), RAW, "round1", "all_development")
    graph_artifact = save_model("graph_free", graph_final, graph_norm)
    manifest = {"training_split": "development", "development_query_count": 1440,
        "seed": RAW["seed"], "same_architecture_and_optimizer_as_frozen_stage3d": True,
        "no_hard_negatives": {"definition": "frozen round-0 hard/diverse negative sample only",
                              "round0_stats": round0_stats, **no_hard_artifact},
        "no_graph_features": {"definition": "remove only relation-graph-derived set-ranker inputs; keep graph upstream",
                              "removed_features": removed, "round0_stats": round0_stats,
                              "round1_stats": round1_stats, **graph_artifact},
        "development_queries_sha256": sha256(PUBLIC / "queries_development.jsonl"),
        "development_gold_sha256": sha256(PUBLIC / "gold_development.jsonl"),
        "full_normalization_sha256": sha256(FULL_NORM),
        "relation_model_for_training": client.config.model,
        "relation_prompt_version": client.config.prompt_version,
        "new_api_requests": 0}
    write_json(OUT / "training_manifest.json", manifest)
    print(json.dumps({"round0": no_hard_artifact["model_sha256"],
                      "graph_free": graph_artifact["model_sha256"]}, indent=2))


def validate(names=("round0", "graph_free")):
    queries, gold = split_data("validation")
    client, retriever = development_runtime()
    scorers = {name: NonlinearSetRanker.load(ARTIFACT / f"{name}.pt",
        ARTIFACT / f"{name}_normalization.json") for name in names}
    metrics, _, cache = evaluate(queries, gold, retriever, scorers)
    if cache["new_http_requests"] or cache["cache_hits"] != cache["relation_cache_lookups"]:
        raise RuntimeError("validation reproduction had relation cache misses")
    for name in names:
        actual = tuple(f"{metrics[name][key]:.4f}" for key in PAPER_METRICS)
        if actual != PAPER_VALIDATION[name]:
            raise RuntimeError(f"{name} does not reproduce the frozen paper validation row: {actual}")
    write_json(OUT / ("restored_model_validation_check.json" if len(names) == 2
                      else "round0_validation_check.json"), metrics)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "train": train()
    elif action == "validate": validate()
    elif action == "validate-round0": validate(("round0",))
    else: raise SystemExit("usage: python -m scripts.train_tef_rag_v6_single_ablation_models train|validate|validate-round0")
