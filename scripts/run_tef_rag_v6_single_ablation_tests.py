"""Frozen retrieval test predictions for the four single TEF-RAG v6 ablations."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_tef_rag_v6_joint_ablation import (PUBLIC, TEST_CACHE, TEST_EVALUATOR_SHA256,
    pair_cache_preflight, read_json, runtime, sha256, split_queries, write_json)
from scripts.run_tef_rag_v6_stage3b import context, features_for, prediction_for
from tef_rag_v6.evaluation import average, evaluate_prediction
from tef_rag_v6.llm_relation import QueryConditionedRelationScorer
from tef_rag_v6.nonlinear_ranknet import NonlinearSetRanker, rank_items
from tef_rag_v6.pair_proposal import LinearPairProposer

OUT = ROOT / "results/v6/single_ablation_tests"
MODEL_DIR = ROOT / "artifacts/v6/single_ablation_tests"
FULL_MODEL = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/model.pt"
FULL_NORM = ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json"
VARIANTS = {
    "no_pair_proposal": ("w/o Pair Proposal", "improved", "full"),
    "no_graph_features": ("w/o Graph Features", "learned", "graph_free"),
    "no_hard_negatives": ("w/o Hard Negatives", "learned", "round0"),
    "no_nonlinear_ranker": ("w/o Nonlinear Ranker", "learned", "greedy"),
}


def configured_runtime(pair_mode: str):
    client, retriever, _, _ = runtime(TEST_CACHE)
    client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected test relation cache miss"))
    if pair_mode == "learned":
        proposer = LinearPairProposer.load(ROOT / "artifacts/v6/stage3a_pair_proposer/model.json")
        retriever.relation_scorer = QueryConditionedRelationScorer(
            client, retriever.config.relation_threshold, proposer, 32)
    elif retriever.relation_scorer.pair_proposer is not None:
        raise RuntimeError("no-pair ablation loaded a learned proposer")
    return client, retriever


def scorer_for(name: str):
    if name == "greedy":
        return None, None, None
    if name == "full":
        model, norm = FULL_MODEL, FULL_NORM
    else:
        model, norm = MODEL_DIR / f"{name}.pt", MODEL_DIR / f"{name}_normalization.json"
    if not model.exists() or not norm.exists():
        raise RuntimeError(f"frozen {name} model artifacts are missing")
    return NonlinearSetRanker.load(model, norm), sha256(model), sha256(norm)


def predict(variant: str):
    name, pair_mode, scorer_name = VARIANTS[variant]
    destination = OUT / f"{variant}_test_predictions.json"
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite frozen predictions: {destination}")
    queries = split_queries("test")
    client, retriever = configured_runtime(pair_mode)
    preflight = pair_cache_preflight(queries, retriever, client)
    if preflight["cache_misses"]:
        raise RuntimeError(f"{preflight['cache_misses']} test relation judgments missing from cache")
    scorer, model_hash, norm_hash = scorer_for(scorer_name)
    predictions, totals = [], Counter()
    for index, query in enumerate(queries, 1):
        public, base, scores, demands, bank = context(query, retriever,
            prefilter_mode=pair_mode, require_cache=True)
        diag = base["relation_diagnostics"]
        if diag["client_failure_pair_count"] or diag["request_count"]:
            raise RuntimeError(f"relation judging failed or made an API request: {query['query_id']}")
        if pair_mode == "improved" and retriever.relation_scorer.pair_proposer is not None:
            raise RuntimeError("learned pair proposer was used")
        if scorer is None or not bank:
            ids = tuple(base["selected_evidence_ids"])
        else:
            items = []
            for candidate_ids in bank:
                aware, _ = features_for(candidate_ids, public, base, scores, demands, retriever, True)
                items.append({"ids": candidate_ids,
                              "agnostic": {k: v for k, v in aware.items() if not k.startswith("relation=")}})
            ids = rank_items(items, scorer)[0]["ids"]
        if (len(ids) > 5 or len(ids) != len(set(ids)) or
                any(not retriever.temporal_eligibility(retriever.by_id[eid], public)[0] or
                    retriever.by_id[eid]["asset_id"] != public["asset_id"] for eid in ids)):
            raise RuntimeError(f"invalid test Top-5: {query['query_id']}")
        final = prediction_for(ids, {**base, "query_text": public["query_text"]}, retriever)
        predictions.append({"query_id": query["query_id"], **final})
        totals.update(lookups=diag["cache_lookup_count"], hits=diag["cache_hit_count"],
                      pair_count=diag["prefiltered_pair_count"], candidate_sets=len(bank))
        if index % 40 == 0:
            print(f"{variant}: {index}/480", flush=True)
    write_json(destination, predictions)
    manifest = {"name": name, "split": "test", "query_count": 480,
        "base_release_commit": "7521229b20e0fa70d4cb42b16f32ebea01778364",
        "pair_prefilter_mode": pair_mode, "set_selector": scorer_name,
        "model_sha256": model_hash, "normalization_sha256": norm_hash,
        "search_pool_k": retriever.config.search_pool_k, "final_k": retriever.config.final_k,
        "pair_budget": retriever.relation_scorer.pair_budget,
        "relation_model": client.config.model, "relation_prompt_version": client.config.prompt_version,
        "relation_temperature": client.config.temperature,
        "relation_confidence_threshold": client.config.llm_confidence_threshold,
        "cache_preflight": preflight, "runtime_diagnostics": dict(totals),
        "test_queries_sha256": sha256(PUBLIC / "queries_test.jsonl"),
        "evidence_sha256": sha256(PUBLIC / "evidence.jsonl"),
        "prediction_sha256": sha256(destination),
        "test_evaluator_accessed_before_prediction_freeze": False}
    write_json(OUT / f"{variant}_test_manifest.json", manifest)


def evaluate(variant: str):
    prediction_path = OUT / f"{variant}_test_predictions.json"
    manifest_path = OUT / f"{variant}_test_manifest.json"
    manifest = read_json(manifest_path)
    if sha256(prediction_path) != manifest["prediction_sha256"]:
        raise RuntimeError("test predictions changed after freeze")
    evaluator = PUBLIC / "test_evaluator.jsonl"
    if sha256(evaluator) != TEST_EVALUATOR_SHA256:
        raise RuntimeError("test evaluator SHA mismatch")
    queries = split_queries("test")
    predictions = read_json(prediction_path)
    if len(predictions) != 480 or [p["query_id"] for p in predictions] != [q["query_id"] for q in queries]:
        raise RuntimeError("test prediction count/order mismatch")
    with evaluator.open(encoding="utf-8-sig") as handle:
        sealed = [json.loads(line) for line in handle if line.strip()]
    gold = {row["query"]["query_id"]: row["gold"] for row in sealed}
    if len(gold) != 480 or set(gold) != {q["query_id"] for q in queries}:
        raise RuntimeError("test evaluator query mismatch")
    metrics = average([evaluate_prediction(row, gold[row["query_id"]], 5) for row in predictions])
    path = OUT / f"{variant}_test_metrics.json"
    write_json(path, metrics)
    manifest.update(test_evaluator_sha256=TEST_EVALUATOR_SHA256,
                    test_evaluator_accessed_after_prediction_freeze=True,
                    test_metrics_sha256=sha256(path))
    write_json(manifest_path, manifest)
    print(json.dumps(metrics, indent=2))


def verify(variant: str):
    name, pair_mode, scorer_name = VARIANTS[variant]
    prediction_path = OUT / f"{variant}_test_predictions.json"
    metrics_path = OUT / f"{variant}_test_metrics.json"
    manifest = read_json(OUT / f"{variant}_test_manifest.json")
    predictions = read_json(prediction_path)
    queries = split_queries("test")
    if (len(predictions) != 480 or
            [row["query_id"] for row in predictions] != [row["query_id"] for row in queries] or
            manifest["name"] != name or manifest["pair_prefilter_mode"] != pair_mode or
            manifest["set_selector"] != scorer_name or
            manifest["prediction_sha256"] != sha256(prediction_path) or
            manifest["test_metrics_sha256"] != sha256(metrics_path) or
            manifest["test_evaluator_sha256"] != TEST_EVALUATOR_SHA256 or
            manifest["cache_preflight"]["cache_misses"] or
            manifest["runtime_diagnostics"]["lookups"] != manifest["runtime_diagnostics"]["hits"]):
        raise RuntimeError(f"{variant} manifest/predictions mismatch")
    _, model_hash, norm_hash = scorer_for(scorer_name)
    if model_hash != manifest["model_sha256"] or norm_hash != manifest["normalization_sha256"]:
        raise RuntimeError(f"{variant} model artifact changed")
    _, retriever = configured_runtime(pair_mode)
    for query, row in zip(queries, predictions):
        ids = row["selected_evidence_ids"]
        public = retriever._public_query(query)
        if (len(ids) > 5 or len(ids) != len(set(ids)) or
                any(eid not in retriever.by_id or
                    not retriever.temporal_eligibility(retriever.by_id[eid], public)[0] or
                    retriever.by_id[eid]["asset_id"] != public["asset_id"] for eid in ids)):
            raise RuntimeError(f"{variant} invalid evidence: {query['query_id']}")
    print(f"verified {variant}: 480 ordered queries, Top-5 and temporal eligibility, artifact hashes, 100% cache hits")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("predict", "evaluate", "verify"))
    parser.add_argument("variant", choices=VARIANTS)
    args = parser.parse_args()
    {"predict": predict, "evaluate": evaluate, "verify": verify}[args.action](args.variant)


if __name__ == "__main__":
    main()
