"""One-shot frozen TEF-RAG v6 sealed prediction and aggregate evaluation runner."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline_adapters.ta_rag_suite_v6 import TARAGRuntime
from scripts.run_tef_rag_v6_stage2a import build_runtime
from scripts.run_tef_rag_v6_stage3a import digest
from scripts.run_tef_rag_v6_stage3b import features_for, prediction_for
from tef_rag_v6.baseline_suite import bge_rerank, bm25_rank, temporal_bm25_rank
from tef_rag_v6.evaluation import average, evaluate_prediction
from tef_rag_v6.llm_relation import LLMRelationClient, LLMRelationConfig, QueryConditionedRelationScorer
from tef_rag_v6.nonlinear_ranknet import NonlinearSetRanker, rank_items
from tef_rag_v6.pair_proposal import LinearPairProposer
from tef_rag_v6.set_scorer import candidate_bank

# Public projection lives here so the prediction runner cannot import a gold-loading runner.

PUBLIC = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/public"
OUT = ROOT / "results/v6/sealed_test"
PRED = OUT / "predictions"
PROGRESS = ROOT / ".cache/tef_rag_v6_sealed_progress"
RELATION_CACHE = ROOT / ".cache/tef_rag_v6_test_relation"
FINAL_FREEZE = ROOT / "results/v6/final_freeze_manifest.json"
DEFAULT_SEALED = ROOT / ".local_sealed/tef_v6_benchmark_v1_test_evaluator.jsonl"
SEALED_SHA256 = "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def public_queries(rows: list[dict]) -> list[dict]:
    allowed = ("query_id", "query_text", "query_time", "asset_id", "asset_model", "asset_context")
    return [{key: row[key] for key in allowed if key in row} for row in rows]


def public_evidence(rows: list[dict]) -> list[dict]:
    allowed = ("evidence_id", "text", "event_time", "available_at", "asset_id", "asset_model",
               "event_type", "source_type", "valid_from", "valid_to", "withdrawn_at", "model_scope",
               "episode_id", "procedure_version", "supersedes", "supersedes_evidence_id")
    return [{key: row[key] for key in allowed if key in row} for row in rows]


def queries() -> list[dict]:
    rows = public_queries(load_jsonl(PUBLIC / "queries_test.jsonl"))
    if len(rows) != 480 or len({row["query_id"] for row in rows}) != 480:
        raise RuntimeError("test query count/uniqueness mismatch")
    return rows


def prediction(query: dict, ids: list[str], relations=None, uncertainty=None) -> dict:
    return {"query_id": query["query_id"], "selected_evidence_ids": list(ids)[:5],
            "relations": relations or [], "uncertainty": uncertainty or {"status": "not_indicated", "evidence_ids": []}}


def frozen_env() -> dict:
    values = {}
    for raw in (ROOT.parent.parent / "local.env").read_text(encoding="utf-8-sig").splitlines():
        if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    if not values.get("API_KEY"):
        raise RuntimeError("local.env API_KEY missing")
    return values


def bge_scorer():
    import torch
    from sentence_transformers import CrossEncoder
    path = ROOT / "experiments/runtime/models/bge-reranker-v2-m3"
    model = CrossEncoder(str(path), trust_remote_code=True, device="cuda" if torch.cuda.is_available() else "cpu")
    return lambda pairs: model.predict(pairs, batch_size=16, show_progress_bar=False)


def run_simple(method: str) -> None:
    qs = queries(); evidence = public_evidence(load_jsonl(PUBLIC / "evidence.jsonl"))
    scorer = bge_scorer() if method == "bge_reranker" else None
    rows = []
    for index, query in enumerate(qs, 1):
        if method == "bm25": ranked = bm25_rank(query, evidence, 5)
        elif method == "bge_reranker": ranked = bge_rerank(query, evidence, scorer, 5)
        else: ranked = temporal_bm25_rank(query, evidence, 0.25, 5)
        rows.append(prediction(query, [item["evidence_id"] for item in ranked]))
        if index % 100 == 0: print(f"{method}: {index}/480", flush=True)
    write_json(PRED / f"{method}.json", rows)


def run_ta() -> None:
    env = frozen_env(); qs = queries(); evidence = public_evidence(load_jsonl(PUBLIC / "evidence.jsonl"))
    progress_path = PROGRESS / "ta_rag.json"
    rows = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else []
    runtime = TARAGRuntime(ROOT / "experiments/runtime/ta_rag_v1", "https://api.deepseek.com",
                           env["API_KEY"], "deepseek-chat",
                           ROOT / "experiments/runtime/models/nomic-embed-text-v1.5",
                           ROOT / "experiments/runtime/models/bge-reranker-v2-m3")
    for index in range(len(rows), len(qs)):
        query = qs[index]
        rows.append(prediction(query, runtime.retrieve(query, evidence, 5)))
        write_json(progress_path, rows)
        if (index + 1) % 50 == 0: print(f"ta_rag: {index + 1}/480", flush=True)
    write_json(PRED / "ta_rag.json", rows)


def tef_runtime():
    env = frozen_env()
    _, base, frozen_relation, _, retriever = build_runtime(ROOT / "configs/tef_rag_v6_stage2a_llm_relation.json")
    proposer = LinearPairProposer.load(ROOT / "artifacts/v6/stage3a_pair_proposer/model.json")
    endpoint = env.get("ENDPOINT", "https://api.deepseek.com/chat/completions")
    relation = replace(frozen_relation, endpoint=endpoint, base_url="https://api.deepseek.com",
        model="deepseek-chat", thinking=None, prompt_version="tef-v6-stage2a-relation-v7",
        temperature=0.0, max_tokens=3500, request_interval_seconds=4.0,
        cache_dir=str(RELATION_CACHE), case_batch_mode=True)
    client = LLMRelationClient(relation, retriever.relation_scorer.client.taxonomy, api_key=env["API_KEY"])
    retriever.config = replace(base, search_pool_k=30, beam_width=8, expansion_top_k=30,
        length_normalization=0.0, connectivity_weight=0.10, uncertainty_weight=0.12,
        relevance_fallback=True, beam_min_gain=1.0)
    retriever.relation_scorer = QueryConditionedRelationScorer(client, 0.6, proposer, 32)
    return retriever


def tef_context(query: dict, retriever):
    pred = retriever.retrieve(query, relation_mode="llm", search_mode="greedy", prefilter_mode="learned")
    public = retriever._public_query(query)
    eligible = [item for item in retriever.candidate_retrieval(public)
                if retriever.temporal_eligibility(item["document"], public)[0]]
    scores = retriever._node_scores(public, eligible)
    pool = pred["search_diagnostics"]["search_pool_ids"]
    demands = retriever._role_demands(public["query_text"])
    raw_ids, _ = retriever._select_flow([{"document": retriever.by_id[value]} for value in pool], scores,
        pred["relation_graph"], demands, use_relations=True, use_flow=True, search_mode="raw_beam")
    bank = candidate_bank(pool, scores, pred["selected_evidence_ids"], raw_ids)
    return public, pred, scores, demands, bank


def run_tef() -> None:
    progress_path = PROGRESS / "tef_rag_stage3d.json"
    if not progress_path.exists() and RELATION_CACHE.exists() and any(RELATION_CACHE.iterdir()):
        raise RuntimeError("first sealed relation cache must start empty")
    qs = queries(); retriever = tef_runtime()
    scorer = NonlinearSetRanker.load(ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/model.pt",
                                     ROOT / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json")
    state = (json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists()
             else {"predictions": [], "stats": {}, "unresolved_query": None})
    rows = state["predictions"]; totals = Counter(state.get("stats", {}))
    for index in range(len(rows), len(qs)):
        query = qs[index]; public, base_prediction, scores, demands, bank = tef_context(query, retriever)
        diag = base_prediction["relation_diagnostics"]
        for key in ("request_count", "retry_count", "cache_hit_count", "cache_lookup_count",
                    "client_failure_pair_count", "prompt_tokens", "completion_tokens"):
            totals[key] += int(diag.get(key, 0))
        if diag.get("client_failure_pair_count", 0):
            write_json(progress_path, {"predictions": rows, "stats": dict(totals),
                                       "unresolved_query": index + 1})
            raise RuntimeError(f"unrecoverable relation failure at query {index + 1}; safe resume required")
        if bank:
            items = []
            for ids in bank:
                aware, hand = features_for(ids, public, base_prediction, scores, demands, retriever, True)
                items.append({"ids": ids, "agnostic": {k: v for k, v in aware.items() if not k.startswith("relation=")}})
            ids = rank_items(items, scorer)[0]["ids"]
        else:
            ids = tuple(base_prediction["selected_evidence_ids"])
        final = prediction_for(ids, {**base_prediction, "query_text": public["query_text"]}, retriever)
        rows.append({"query_id": query["query_id"], **final})
        write_json(progress_path, {"predictions": rows, "stats": dict(totals), "unresolved_query": None})
        if (index + 1) % 20 == 0: print(f"tef_rag_stage3d: {index + 1}/480", flush=True)
    write_json(PRED / "tef_rag_stage3d.json", rows)


def validate_prediction_files() -> dict:
    qs = queries(); expected = [row["query_id"] for row in qs]; hashes = {}
    for method in METHODS:
        path = PRED / f"{method}.json"; rows = json.loads(path.read_text(encoding="utf-8"))
        if len(rows) != 480 or [row.get("query_id") for row in rows] != expected:
            raise RuntimeError(f"{method} query IDs/count mismatch")
        for row in rows:
            if set(row) - {"query_id", "selected_evidence_ids", "relations", "uncertainty"}:
                raise RuntimeError(f"{method} prediction has forbidden fields")
            if len(row["selected_evidence_ids"]) > 5 or len(row["selected_evidence_ids"]) != len(set(row["selected_evidence_ids"])):
                raise RuntimeError(f"{method} invalid Top-5")
        hashes[method] = sha256(path)
    return hashes


def freeze_predictions() -> None:
    hashes = validate_prediction_files()
    stats_path = PROGRESS / "tef_rag_stage3d.json"
    progress = json.loads(stats_path.read_text(encoding="utf-8")); stats = progress["stats"]
    if progress.get("unresolved_query") is not None or len(progress.get("predictions", [])) != 480:
        raise RuntimeError("unresolved relation query prevents prediction freeze")
    manifest = {"status": "PREDICTIONS_FROZEN_BEFORE_SEALED_EVALUATION",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "test_query_count": 480,
        "query_ids_sha256": digest([row["query_id"] for row in queries()]),
        "final_freeze_reference": sha256(FINAL_FREEZE),
        "predictions": {method: {"method": method, "query_count": 480, "prediction_sha256": value}
                        for method, value in hashes.items()},
        "relation_cache_statistics": {"llm_request_count": stats.get("request_count", 0),
            "retry_count": stats.get("retry_count", 0), "cache_hit_count": stats.get("cache_hit_count", 0),
            "cache_lookup_count": stats.get("cache_lookup_count", 0),
            "failure_count": stats.get("client_failure_pair_count", 0),
            "prompt_tokens": stats.get("prompt_tokens", 0), "completion_tokens": stats.get("completion_tokens", 0)},
        "sealed_evaluator_accessed": False}
    write_json(OUT / "prediction_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


def evaluate(sealed: Path) -> None:
    manifest_path = OUT / "prediction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = validate_prediction_files()
    if any(manifest["predictions"][key]["prediction_sha256"] != value for key, value in current.items()):
        raise RuntimeError("prediction changed after freeze")
    if sha256(sealed) != SEALED_SHA256:
        raise RuntimeError("sealed evaluator SHA mismatch")
    gold_rows = load_jsonl(sealed)
    gold = {row["query"]["query_id"]: row["gold"] for row in gold_rows}
    if len(gold) != 480:
        raise RuntimeError("sealed evaluator query count mismatch")
    values = {}
    for method in METHODS:
        rows = json.loads((PRED / f"{method}.json").read_text(encoding="utf-8"))
        scored = [evaluate_prediction(row, gold[row["query_id"]], 5) for row in rows]
        aggregate = average(scored)
        if method != "tef_rag_stage3d": aggregate["edge_recall"] = None
        values[method] = aggregate
    write_json(OUT / "metrics.json", values)
    final = {"final_freeze_commit": "5f32d436fd1611b9835322846ba19667894305fb",
        "benchmark_seal_commit": "4cd74c51bf874beac3c72df7fa64ae89f73438b8",
        "sealed_evaluator_sha256": SEALED_SHA256, "prediction_sha256s": current,
        "test_query_count": 480, "method_configs": json.loads(FINAL_FREEZE.read_text(encoding="utf-8"))["baselines"],
        "relation_runtime": {"transport_substitution": "official DeepSeek API", "prompt_version": "tef-v6-stage2a-relation-v7"},
        "relation_cache_statistics": manifest["relation_cache_statistics"], "sealed_evaluation_count": 1,
        "target_method_test_runs": 1, "known_benchmark_issue": "BENCHMARK_ISSUE_FOUND",
        "prediction_manifest_sha256": sha256(manifest_path)}
    write_json(OUT / "final_evaluation_manifest.json", final)
    print(json.dumps(values, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("predict", "freeze", "evaluate"))
    parser.add_argument("--method", choices=METHODS)
    parser.add_argument("--evaluator", type=Path, default=DEFAULT_SEALED)
    args = parser.parse_args()
    if args.action == "predict":
        if not args.method: raise SystemExit("predict requires --method")
        if (OUT / "prediction_manifest.json").exists(): raise RuntimeError("predictions already frozen")
        if args.method in {"bm25", "bge_reranker", "temporal_bm25"}: run_simple(args.method)
        elif args.method == "ta_rag": run_ta()
        else: run_tef()
    elif args.action == "freeze": freeze_predictions()
    else: evaluate(args.evaluator)


if __name__ == "__main__":
    main()
