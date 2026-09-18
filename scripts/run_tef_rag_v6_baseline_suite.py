"""Run development selection, freeze, then one guarded validation baseline pass."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tef_rag_v6.baseline_suite import bge_rerank, bm25_rank, temporal_bm25_rank
from tef_rag_v6.evaluation import average, evaluate_prediction

PUBLIC = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/public"
OUT = ROOT / "results/v6/baseline_suite"
LAMBDAS = (0.25, 0.50, 0.75)
BGE_MODEL = "BAAI/bge-reranker-v2-m3"
BGE_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
NOMIC_MODEL = "nomic-ai/nomic-embed-text-v1.5"
TA_COMMIT = "9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9"
STAGE3D_COMMIT = "716e5660bde8f2ed84d2b48d8464d8b071b50874"
BENCHMARK_COMMIT = "e439621d2598fda2d2bc165b5679641e42a36321"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def public_queries(rows: list[dict]) -> list[dict]:
    fields = ("query_id", "query_text", "query_time", "asset_id", "asset_model", "asset_context")
    return [{key: row[key] for key in fields if key in row} for row in rows]


def public_evidence(rows: list[dict]) -> list[dict]:
    fields = ("evidence_id", "text", "event_time", "available_at", "asset_id", "asset_model",
              "event_type", "source_type", "valid_from", "valid_to", "withdrawn_at", "model_scope")
    return [{key: row[key] for key in fields if key in row} for row in rows]


def digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def code_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def prediction(query: dict, ids: list[str]) -> dict:
    return {"query_id": query["query_id"], "selected_evidence_ids": ids[:5], "relations": []}


def metrics(predictions: list[dict], gold: list[dict]) -> dict:
    by_id = {row["query_id"]: row for row in gold}
    return average([evaluate_prediction(row, by_id[row["query_id"]]) for row in predictions])


def run_method(queries, evidence, method, scorer=None, lambda_=None):
    output = []
    started = time.time()
    for number, query in enumerate(queries, 1):
        if method == "bm25":
            rows = bm25_rank(query, evidence, 5)
            ids = [row["evidence_id"] for row in rows]
        elif method == "bge_reranker":
            rows = bge_rerank(query, evidence, scorer, 5)
            ids = [row["evidence_id"] for row in rows]
        elif method == "temporal_bm25":
            rows = temporal_bm25_rank(query, evidence, lambda_, 5)
            ids = [row["evidence_id"] for row in rows]
        else:
            ids = scorer.retrieve(query, evidence, 5)
        output.append(prediction(query, ids))
        if number % 100 == 0:
            print(f"{method}: {number}/{len(queries)}", flush=True)
    return output, time.time() - started


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def package_versions() -> dict:
    names = ["numpy", "torch", "transformers", "sentence-transformers", "faiss-cpu", "ncls", "openai"]
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def bge_scorer(model_path: str):
    from sentence_transformers import CrossEncoder
    import torch
    model = CrossEncoder(model_path, trust_remote_code=True,
                         device="cuda" if torch.cuda.is_available() else "cpu")
    return lambda pairs: model.predict(pairs, batch_size=16, show_progress_bar=False)


def ta_runtime(args):
    from baseline_adapters.ta_rag_suite_v6 import TARAGRuntime
    return TARAGRuntime(args.ta_upstream, args.ta_base_url, os.environ.get("TA_RAG_API_KEY", ""),
                        args.ta_model, args.nomic_path, args.bge_path)


def development(args) -> None:
    queries = public_queries(load_jsonl(PUBLIC / "queries_development.jsonl"))
    gold = load_jsonl(PUBLIC / "gold_development.jsonl")
    evidence = public_evidence(load_jsonl(PUBLIC / "evidence.jsonl"))
    target = OUT / "development"
    selected_methods = set(args.methods.split(","))
    all_metrics = read_json(target / "metrics.json", {})
    runtimes = read_json(target / "runtime.json", {})
    failures = read_json(target / "failures.json", {})
    for method, scorer in (("bm25", None),
                           ("bge_reranker", bge_scorer(args.bge_path) if "bge_reranker" in selected_methods else None)):
        if method not in selected_methods:
            continue
        rows, elapsed = run_method(queries, evidence, method, scorer)
        all_metrics[method], runtimes[method] = metrics(rows, gold), elapsed
        failures.pop(method, None)
        write_json(target / f"predictions_{method}.json", rows)
    prior_temporal = read_json(target / "temporal_lambda_selection.json", {})
    temporal = prior_temporal.get("candidates", {})
    selected = prior_temporal.get("selected")
    if "temporal_bm25" in selected_methods:
        for value in LAMBDAS:
            rows, elapsed = run_method(queries, evidence, "temporal_bm25", lambda_=value)
            temporal[str(value)] = metrics(rows, gold)
            runtimes[f"temporal_bm25_{value}"] = elapsed
            write_json(target / f"predictions_temporal_bm25_{value}.json", rows)
        selected = sorted(LAMBDAS, key=lambda value: (-temporal[str(value)]["flow_complete_at_5"],
                          -temporal[str(value)]["complete_at_5"], -temporal[str(value)]["recall_at_5"], -value))[0]
        all_metrics["temporal_bm25"] = temporal[str(selected)]
        write_json(target / "temporal_lambda_selection.json", {"candidates": temporal, "selected": selected})
    if "ta_rag" in selected_methods:
        try:
            runtime = ta_runtime(args)
            rows, elapsed = run_method(queries, evidence, "ta_rag", runtime)
            all_metrics["ta_rag"], runtimes["ta_rag"] = metrics(rows, gold), elapsed
            failures.pop("ta_rag", None)
            write_json(target / "predictions_ta_rag.json", rows)
        except Exception as exc:
            failures["ta_rag"] = f"{type(exc).__name__}: {exc}"
    write_json(target / "metrics.json", all_metrics)
    write_json(target / "runtime.json", runtimes)
    write_json(target / "failures.json", failures)
    missing = sorted({"bm25", "bge_reranker", "temporal_bm25", "ta_rag"} - set(all_metrics))
    freeze = {
        "status": "FROZEN" if not failures and not missing else "INCOMPLETE_BLOCKED",
        "benchmark_commit": BENCHMARK_COMMIT, "baseline_code_commit": code_commit(),
        "stage3d_commit": STAGE3D_COMMIT,
        "bm25": {"implementation": "tef_rag_v6.pipeline.BM25Index", "k1": 1.5, "b": 0.75},
        "bge": {"model": BGE_MODEL, "revision": BGE_REVISION, "candidate_depth": 30},
        "temporal_bm25": {"formula": "lambda*normalized_bm25+(1-lambda)*temporal_score",
                          "lambda": selected, "lambda_candidates": list(LAMBDAS)},
        "ta_rag": {"upstream_commit": TA_COMMIT, "embedding": NOMIC_MODEL,
                   "base_url": args.ta_base_url, "model": args.ta_model, "temperature": 0,
                   "api_key_persisted": False},
        "dependencies": package_versions(), "top_k": 5, "failures": failures, "missing": missing,
    }
    freeze["freeze_hash"] = digest(freeze)
    write_json(OUT / "baseline_freeze.json", freeze)


def validation(args) -> None:
    freeze_path = OUT / "baseline_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    expected = freeze.pop("freeze_hash")
    if digest(freeze) != expected or freeze["status"] != "FROZEN":
        raise RuntimeError("validation refused: freeze manifest mismatch or incomplete development")
    marker = OUT / "validation/.formal_run_complete"
    if marker.exists():
        raise RuntimeError("validation refused: formal validation already ran")
    if args.bge_path is None or args.nomic_path is None:
        raise RuntimeError("validation requires the exact frozen local model paths")
    queries = public_queries(load_jsonl(PUBLIC / "queries_validation.jsonl"))
    gold = load_jsonl(PUBLIC / "gold_validation.jsonl")
    evidence = public_evidence(load_jsonl(PUBLIC / "evidence.jsonl"))
    scorers = {"bge_reranker": bge_scorer(args.bge_path), "ta_rag": ta_runtime(args)}
    values = {}
    for method in ("bm25", "bge_reranker", "temporal_bm25", "ta_rag"):
        rows, elapsed = run_method(queries, evidence, method, scorers.get(method),
                                   freeze["temporal_bm25"]["lambda"] if method == "temporal_bm25" else None)
        values[method] = metrics(rows, gold)
        write_json(OUT / "validation" / f"predictions_{method}.json", rows)
    values["tef_rag_stage3d"] = json.loads((ROOT / "results/v6/stage3d_nonlinear_ranknet/ranking_metrics_validation.json").read_text())["frozen_mlp"]
    write_json(OUT / "validation/metrics.json", values)
    marker.write_text(expected + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("split", choices=("development", "validation"))
    parser.add_argument("--bge-path", default=str(ROOT / "experiments/runtime/models/bge-reranker-v2-m3"))
    parser.add_argument("--nomic-path", default=str(ROOT / "experiments/runtime/models/nomic-embed-text-v1.5"))
    parser.add_argument("--ta-upstream", default=str(ROOT / "experiments/runtime/ta_rag_v1"))
    parser.add_argument("--ta-base-url", default="http://127.0.0.1:55555/v1")
    parser.add_argument("--ta-model", default="deepseek-chat")
    parser.add_argument("--methods", default="bm25,bge_reranker,temporal_bm25,ta_rag")
    args = parser.parse_args()
    development(args) if args.split == "development" else validation(args)


if __name__ == "__main__":
    main()
