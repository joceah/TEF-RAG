"""CLI orchestration for frozen TEF-RAG v6 generation evaluation."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tef_rag_v6.generation_eval import (
    Canonicalizer,
    evaluate_generation_prediction,
    macro_average,
    validate_generation_output,
)
from tef_rag_v6.generation_runner import (
    PUBLIC,
    GEN_META,
    OUT,
    PRED_OUT,
    CACHE,
    RETRIEVAL_MANIFEST,
    DEFAULT_PRIVATE,
    METHODS,
    MODEL,
    BASE_URL,
    TEMPERATURE,
    PROMPT_VERSION,
    GENERATION_PROTOCOL_VERSION,
    DeepSeekClient,
    aliases,
    build_prompt,
    evidence_map,
    generator_instructions,
    parameters,
    queries,
    read_json,
    read_jsonl,
    repair_prompt,
    retrieval_paths,
    retrieval_predictions,
    schema,
    sha256,
    sha_text,
    visible_at,
    write_json,
    write_jsonl,
)


def expected_retrieval_hashes() -> dict[str, str]:
    manifest = read_json(RETRIEVAL_MANIFEST)
    return {method: manifest["predictions"][method]["prediction_sha256"] for method in METHODS}


def preflight() -> dict[str, Any]:
    required = [
        PUBLIC / "queries_test.jsonl",
        PUBLIC / "evidence.jsonl",
        RETRIEVAL_MANIFEST,
        GEN_META / "schema.json",
        GEN_META / "alias_registry.json",
        GEN_META / "parameter_registry.json",
        GEN_META / "test_generation_gold_aggregate.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("missing required files: " + "; ".join(missing))

    qs = queries()
    qids = [query["query_id"] for query in qs]
    evidence = evidence_map()
    expected_hashes = expected_retrieval_hashes()
    problems: list[str] = []
    for method, path in retrieval_paths().items():
        if not path.exists():
            problems.append(f"{method}: missing retrieval prediction")
            continue
        if sha256(path) != expected_hashes[method]:
            problems.append(f"{method}: retrieval hash changed")
        rows = read_json(path)
        if len(rows) != 480 or [row.get("query_id") for row in rows] != qids:
            problems.append(f"{method}: query order/count mismatch")
            continue
        for query, row in zip(qs, rows):
            ids = row.get("selected_evidence_ids", [])
            if len(ids) != 5 or len(set(ids)) != 5:
                problems.append(f"{method}/{query['query_id']}: expected exactly 5 unique evidence IDs")
                continue
            for evidence_id in ids:
                if evidence_id not in evidence:
                    problems.append(f"{method}/{query['query_id']}: unknown evidence {evidence_id}")
                elif not visible_at(evidence[evidence_id], query):
                    problems.append(f"{method}/{query['query_id']}: non-visible evidence {evidence_id}")
    if problems:
        raise RuntimeError("preflight failed:\n- " + "\n- ".join(problems[:30]))

    aggregate = read_json(GEN_META / "test_generation_gold_aggregate.json")
    result = {
        "status": "READY_FOR_GENERATION",
        "test_queries": 480,
        "methods": list(METHODS),
        "retrieval_prediction_hashes": expected_hashes,
        "generation_schema_sha256": sha256(GEN_META / "schema.json"),
        "alias_registry_sha256": sha256(GEN_META / "alias_registry.json"),
        "parameter_registry_sha256": sha256(GEN_META / "parameter_registry.json"),
        "private_generation_gold_expected_sha256": aggregate["private_gold_sha256"],
        "private_generation_gold_accessed": False,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        "temperature": TEMPERATURE,
    }
    write_json(OUT / "preflight.json", result)
    return result


def load_generation_rows(method: str) -> list[dict[str, Any]]:
    path = PRED_OUT / f"{method}.jsonl"
    return read_jsonl(path) if path.exists() else []


def run_generation(methods: tuple[str, ...]) -> dict[str, Any]:
    if (OUT / "generation_prediction_manifest.json").exists():
        raise RuntimeError("generation predictions already frozen")
    preflight()
    qs = queries()
    evidence = evidence_map()
    retrieval = retrieval_predictions()
    output_schema = schema()
    client = DeepSeekClient(CACHE / "api_cache")
    existing = {method: load_generation_rows(method) for method in methods}

    for method in methods:
        if any(row.get("query_id") != qs[index]["query_id"] for index, row in enumerate(existing[method])):
            raise RuntimeError(f"{method}: existing generation progress query order mismatch")

    for index, query in enumerate(qs):
        for method in methods:
            if len(existing[method]) > index:
                continue
            retrieval_row = retrieval[method][index]
            selected_ids = list(retrieval_row["selected_evidence_ids"])
            selected = [evidence[evidence_id] for evidence_id in selected_ids]
            system, user = build_prompt(query, selected, output_schema)
            initial = client.call(system, user, f"generate:{method}:{query['query_id']}")
            errors = validate_generation_output(initial, output_schema, set(selected_ids), query["asset_id"])
            repair_used = False
            final = initial
            if errors:
                repair_used = True
                repair_system, repair_user = repair_prompt(query, selected, initial, errors, output_schema)
                final = client.call(repair_system, repair_user, f"repair:{method}:{query['query_id']}")
                errors = validate_generation_output(final, output_schema, set(selected_ids), query["asset_id"])
            row = {
                "query_id": query["query_id"],
                "input_evidence_ids": selected_ids,
                "generation": final,
                "repair_used": repair_used,
                "validation_errors": errors,
            }
            existing[method].append(row)
            write_jsonl(PRED_OUT / f"{method}.jsonl", existing[method])
        if (index + 1) % 20 == 0:
            print(f"generation: {index + 1}/480 queries x {len(methods)} methods", flush=True)

    unresolved = {
        method: sum(bool(row["validation_errors"]) for row in rows)
        for method, rows in existing.items()
    }
    runtime = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "methods": list(methods),
        "client_stats": client.stats,
        "unresolved": unresolved,
    }
    write_json(OUT / "generation_runtime.json", runtime)
    if any(unresolved.values()):
        raise RuntimeError("generation completed with unresolved outputs: " + json.dumps(unresolved))
    return runtime


def validate_generation_files() -> dict[str, str]:
    qs = queries()
    retrieval = retrieval_predictions()
    output_schema = schema()
    hashes: dict[str, str] = {}
    for method in METHODS:
        path = PRED_OUT / f"{method}.jsonl"
        if not path.exists():
            raise RuntimeError(f"missing generation output: {method}")
        rows = read_jsonl(path)
        if len(rows) != 480:
            raise RuntimeError(f"{method}: expected 480 generation rows")
        for index, (query, row) in enumerate(zip(qs, rows)):
            if row.get("query_id") != query["query_id"]:
                raise RuntimeError(f"{method}: query order mismatch at {index}")
            selected = list(retrieval[method][index]["selected_evidence_ids"])
            if row.get("input_evidence_ids") != selected:
                raise RuntimeError(f"{method}/{query['query_id']}: retrieval input changed")
            errors = validate_generation_output(
                row.get("generation"),
                output_schema,
                set(selected),
                query["asset_id"],
            )
            if errors or row.get("validation_errors"):
                raise RuntimeError(
                    f"{method}/{query['query_id']}: invalid generation output: "
                    f"{errors or row.get('validation_errors')}"
                )
        hashes[method] = sha256(path)
    return hashes


def freeze() -> dict[str, Any]:
    pre = preflight()
    hashes = validate_generation_files()
    runtime = read_json(OUT / "generation_runtime.json") if (OUT / "generation_runtime.json").exists() else {}
    manifest = {
        "status": "GENERATION_PREDICTIONS_FROZEN_BEFORE_PRIVATE_GOLD_ACCESS",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "methods": list(METHODS),
        "query_count_per_method": 480,
        "generator": {
            "base_url": BASE_URL,
            "model": MODEL,
            "temperature": TEMPERATURE,
            "prompt_version": PROMPT_VERSION,
            "repair_policy": "one repair max",
        },
        "protocol_version": GENERATION_PROTOCOL_VERSION,
        "retrieval_prediction_hashes": pre["retrieval_prediction_hashes"],
        "generation_prediction_hashes": hashes,
        "schema_sha256": pre["generation_schema_sha256"],
        "alias_registry_sha256": pre["alias_registry_sha256"],
        "parameter_registry_sha256": pre["parameter_registry_sha256"],
        "prompt_sha256": sha_text(generator_instructions()),
        "private_generation_gold_expected_sha256": pre["private_generation_gold_expected_sha256"],
        "private_generation_gold_accessed": False,
        "retrieval_relations_passed_to_generator": False,
        "method_identity_passed_to_generator": False,
        "runtime": runtime.get("client_stats", {}),
    }
    write_json(OUT / "generation_prediction_manifest.json", manifest)
    return manifest


def load_private_gold(root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    gold_path = root / "gold_test.jsonl"
    index_path = root / "gold_test_index.jsonl"
    if not gold_path.exists() or not index_path.exists():
        raise RuntimeError("private generation gold/index missing")
    expected = read_json(GEN_META / "test_generation_gold_aggregate.json")["private_gold_sha256"]
    actual = sha256(gold_path)
    if actual != expected:
        raise RuntimeError(f"private generation gold SHA mismatch: {actual}")
    gold_rows = read_jsonl(gold_path)
    index_rows = read_jsonl(index_path)
    if len(gold_rows) != 240 or len(index_rows) != 240:
        raise RuntimeError("expected 240 semantic private gold objects")
    by_query: dict[str, dict[str, Any]] = {}
    for gold, index in zip(gold_rows, index_rows):
        for query_id in index.get("query_ids", []):
            if query_id in by_query:
                raise RuntimeError(f"duplicate private gold query id {query_id}")
            by_query[query_id] = gold
    if len(by_query) != 480:
        raise RuntimeError("private gold index must cover 480 query rows")
    return by_query, actual


def evaluate(private_root: Path) -> dict[str, Any]:
    manifest_path = OUT / "generation_prediction_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("freeze generation predictions before evaluation")
    manifest = read_json(manifest_path)
    current = validate_generation_files()
    if current != manifest["generation_prediction_hashes"]:
        raise RuntimeError("generation predictions changed after freeze")

    by_query, gold_hash = load_private_gold(private_root)
    if gold_hash != manifest["private_generation_gold_expected_sha256"]:
        raise RuntimeError("private gold differs from frozen expectation")

    qs = queries()
    retrieval = retrieval_predictions()
    output_schema = schema()
    canon = Canonicalizer(aliases(), parameters())
    metrics: dict[str, Any] = {}
    private_details = private_root / "evaluation_details_v1"
    private_details.mkdir(parents=True, exist_ok=True)

    for method in METHODS:
        rows = read_jsonl(PRED_OUT / f"{method}.jsonl")
        scored: list[dict[str, Any]] = []
        for index, (query, row) in enumerate(zip(qs, rows)):
            gold = by_query[query["query_id"]]
            values = evaluate_generation_prediction(
                row["generation"],
                gold,
                output_schema,
                canon,
                set(retrieval[method][index]["selected_evidence_ids"]),
                query["asset_id"],
            )
            scored.append({"query_id": query["query_id"], **values})
        write_jsonl(private_details / f"{method}.jsonl", scored)
        metrics[method] = macro_average([
            {key: value for key, value in row.items() if key != "query_id"}
            for row in scored
        ])

    write_json(OUT / "metrics.json", metrics)
    final = {
        "status": "GENERATION_EVALUATION_COMPLETE",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "generation_prediction_manifest_sha256": sha256(manifest_path),
        "generation_prediction_hashes": current,
        "private_generation_gold_sha256": gold_hash,
        "private_item_level_scores_written_outside_repo": True,
        "aggregate_metrics_path": str((OUT / "metrics.json").relative_to(ROOT)),
        "methods": list(METHODS),
        "query_count_per_method": 480,
        "evaluation_count": 1,
        "protocol_version": GENERATION_PROTOCOL_VERSION,
    }
    write_json(OUT / "final_evaluation_manifest.json", final)
    return metrics
