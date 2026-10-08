"""Run only the selected supervised BGE retrieval through the frozen generator."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_tef_rag_v6_public_generation import evaluate_method, load_gold
from scripts.evaluate_tef_rag_v6_public_retrieval import (
    _load_public_inputs, validate_prediction_rows,
)
from tef_rag_v6.generation_eval import Canonicalizer, validate_generation_output
from tef_rag_v6.generation_runner import (
    BASE_URL, CACHE, DeepSeekClient, GEN_META, MODEL, PROMPT_VERSION,
    GENERATION_PROTOCOL_VERSION, build_prompt, generator_instructions,
    read_json, read_jsonl, repair_prompt, request_fingerprint, sha256,
    sha_text, validate_parse_provenance, write_json, write_jsonl,
)

OUT = ROOT / "results/v6/supervised_bge_reranker"
RETRIEVAL = OUT / "test_retrieval_predictions.json"
PREDICTION = OUT / "generation_predictions.jsonl"
PUBLIC = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public"
GEN = ROOT / "data/generation"


def inputs():
    if not (OUT / "training_manifest.json").exists() or not (OUT / "test_retrieval_metrics.json").exists():
        raise RuntimeError("selected checkpoint and complete retrieval test required")
    queries = read_jsonl(PUBLIC / "queries_test.jsonl")
    evidence_rows = read_jsonl(PUBLIC / "evidence.jsonl")
    evidence = {row["evidence_id"]: row for row in evidence_rows}
    retrieval = read_json(RETRIEVAL)
    expected = [q["query_id"] for q in queries]
    if len(expected) != 480 or len(set(expected)) != 480:
        raise RuntimeError("expected exactly 480 unique test queries")
    query_by_id, evidence_by_id = _load_public_inputs(PUBLIC / "queries_test.jsonl", PUBLIC / "evidence.jsonl")
    validate_prediction_rows("supervised_bge_reranker", retrieval, expected, query_by_id, evidence_by_id)
    if [q["query_id"] for q in queries] != expected:
        raise RuntimeError("query order mismatch")
    return queries, evidence, retrieval


def run():
    queries, evidence, retrieval = inputs()
    output_schema = read_json(GEN / "schema.json")
    session = sha_text(json.dumps({
        "retrieval_sha256": sha256(RETRIEVAL), "model": MODEL,
        "generator_prompt_sha256": sha_text(generator_instructions()),
        "schema_sha256": sha256(GEN / "schema.json"),
        "protocol": GENERATION_PROTOCOL_VERSION,
    }, sort_keys=True))
    existing = read_jsonl(PREDICTION) if PREDICTION.exists() else []
    if len(existing) > 480:
        raise RuntimeError("generation progress exceeds 480 rows")
    for index, row in enumerate(existing):
        ids = retrieval[index]["selected_evidence_ids"]
        if (row.get("query_id") != queries[index]["query_id"] or
                row.get("input_evidence_ids") != ids or row.get("session_fingerprint") != session):
            raise RuntimeError("generation resume fingerprint or evidence mismatch")
        system, user = build_prompt(queries[index], [evidence[eid] for eid in ids], output_schema)
        if row.get("initial_request_fingerprint") != request_fingerprint(BASE_URL + "/chat/completions", system, user):
            raise RuntimeError("generation resume prompt mismatch")
    client = DeepSeekClient(OUT / "api_cache", official=True, diagnostic_dir=OUT / "diagnostics")
    for index in range(len(existing), 480):
        query = queries[index]
        ids = retrieval[index]["selected_evidence_ids"]
        selected = [evidence[eid] for eid in ids]
        system, user = build_prompt(query, selected, output_schema)
        initial_hash = request_fingerprint(client.endpoint, system, user)
        initial = client.call(system, user, f"generate:supervised_bge_reranker:{query['query_id']}")
        if client.last_request_hash != initial_hash or validate_parse_provenance(client.last_parse_provenance):
            raise RuntimeError("initial request/parse provenance mismatch")
        initial_parse = client.last_parse_provenance
        errors = validate_generation_output(initial, output_schema, set(ids), query["asset_id"])
        final = initial
        repair_hash = None
        repair_parse = None
        if errors:
            repair_system, repair_user = repair_prompt(query, selected, initial, errors, output_schema)
            repair_hash = request_fingerprint(client.endpoint, repair_system, repair_user)
            final = client.call(repair_system, repair_user, f"repair:supervised_bge_reranker:{query['query_id']}")
            repair_parse = client.last_parse_provenance
            if client.last_request_hash != repair_hash or validate_parse_provenance(repair_parse):
                raise RuntimeError("repair request/parse provenance mismatch")
        row = {
            "query_id": query["query_id"], "input_evidence_ids": ids, "generation": final,
            "repair_used": bool(errors),
            "validation_errors": validate_generation_output(final, output_schema, set(ids), query["asset_id"]),
            "session_fingerprint": session, "initial_request_fingerprint": initial_hash,
            "repair_request_fingerprint": repair_hash,
            "initial_parse_provenance": initial_parse, "repair_parse_provenance": repair_parse,
            "request_provenance": {"model": MODEL, "prompt_version": PROMPT_VERSION,
                                   "protocol_version": GENERATION_PROTOCOL_VERSION,
                                   "schema_sha256": sha256(GEN / "schema.json")},
        }
        existing.append(row)
        write_jsonl(PREDICTION, existing)
        if (index + 1) % 20 == 0:
            print(f"generation: {index + 1}/480", flush=True)
    write_json(OUT / "generation_runtime.json", {"rows": len(existing), "client_stats": client.stats,
                                                   "prediction_sha256": sha256(PREDICTION),
                                                   "retrieval_sha256": sha256(RETRIEVAL),
                                                   "session_fingerprint": session})


def evaluate():
    queries, evidence, retrieval = inputs()
    generation = read_jsonl(PREDICTION)
    if len(generation) != 480:
        raise RuntimeError("generation must cover all 480 queries")
    for source, output in zip(retrieval, generation):
        if source["query_id"] != output["query_id"] or source["selected_evidence_ids"] != output["input_evidence_ids"]:
            raise RuntimeError("retrieval/generation evidence mismatch")
    gold = load_gold(GEN / "gold_test.jsonl", GEN / "gold_test_index.jsonl")
    canon = Canonicalizer(read_json(GEN / "alias_registry.json"), read_json(GEN / "parameter_registry.json"))
    metrics = evaluate_method(PREDICTION, gold, {q["query_id"]: q for q in queries},
                              read_json(GEN / "schema.json"), canon, evidence)
    write_json(OUT / "generation_metrics.json", {"metrics": metrics,
                                                  "prediction_sha256": sha256(PREDICTION),
                                                  "retrieval_sha256": sha256(RETRIEVAL)})
    print(json.dumps(metrics, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("generate", "evaluate"))
    args = parser.parse_args()
    run() if args.action == "generate" else evaluate()


if __name__ == "__main__":
    main()
