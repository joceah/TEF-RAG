"""CLI orchestration for frozen TEF-RAG v6 generation evaluation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tef_rag_v6.generation_eval import (
    Canonicalizer,
    evaluate_generation_prediction,
    macro_average,
    validate_gold_action_uniqueness,
    validate_generation_output,
)
from tef_rag_v6.generation_runner import (
    ROOT,
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
    MAX_TOKENS,
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
    request_fingerprint,
    retrieval_paths,
    retrieval_predictions,
    schema,
    sha256,
    sha_text,
    visible_at,
    write_json,
    write_jsonl,
)

EVALUATOR_FILES = (
    "tef_rag_v6/generation_eval.py",
    "tef_rag_v6/generation_eval_cli.py",
    "tef_rag_v6/generation_runner.py",
    "scripts/run_tef_rag_v6_generation_eval.py",
)
OFFICIAL_ENDPOINT = BASE_URL.rstrip("/") + "/chat/completions"


def scoring_fingerprint() -> dict[str, Any]:
    return {
        "schema_sha256": sha256(GEN_META / "schema.json"),
        "alias_registry_sha256": sha256(GEN_META / "alias_registry.json"),
        "parameter_registry_sha256": sha256(GEN_META / "parameter_registry.json"),
        "evaluator_sha256": {name: sha256(ROOT / name) for name in EVALUATOR_FILES},
        "protocol_version": GENERATION_PROTOCOL_VERSION,
    }


def formal_session_fingerprint(pre: dict[str, Any]) -> str:
    payload = {
        "protocol_version": GENERATION_PROTOCOL_VERSION,
        "runner_sha256": sha256(ROOT / "tef_rag_v6/generation_runner.py"),
        "instructions_sha256": sha_text(generator_instructions()),
        "schema_sha256": sha256(GEN_META / "schema.json"),
        "model": MODEL,
        "endpoint": OFFICIAL_ENDPOINT,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "retrieval_prediction_hashes": pre["retrieval_prediction_hashes"],
        "materialized_artifact_hashes": pre["materialized_artifact_hashes"],
        "retrieval_manifest_sha256": sha256(RETRIEVAL_MANIFEST),
    }
    return sha_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def expected_retrieval_hashes() -> dict[str, str]:
    manifest = read_json(RETRIEVAL_MANIFEST)
    return {method: manifest["predictions"][method]["prediction_sha256"] for method in METHODS}


def validate_selected_evidence_ids(
    query: dict[str, Any],
    prediction: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate a frozen retrieval row without requiring a full Top-5 result.

    Top-5 is the retrieval budget upper bound.  A sealed row may contain any
    number of unique, visible evidence IDs from zero through that bound, and
    the exact list is passed downstream unchanged.
    """
    ids = prediction.get("selected_evidence_ids")
    if not isinstance(ids, list):
        return ["selected_evidence_ids must be a list"]
    problems: list[str] = []
    if len(ids) > 5:
        problems.append("selected_evidence_ids exceeds Top-5 budget")
    if any(not isinstance(evidence_id, str) for evidence_id in ids):
        problems.append("selected_evidence_ids must contain only strings")
    else:
        if len(ids) != len(set(ids)):
            problems.append("selected_evidence_ids contains duplicates")
        for evidence_id in ids:
            record = evidence.get(evidence_id)
            if record is None:
                problems.append(f"unknown evidence {evidence_id}")
            elif not visible_at(record, query):
                problems.append(f"non-visible evidence {evidence_id}")
    return problems


def preflight() -> dict[str, Any]:
    required = [
        PUBLIC / "queries_test.jsonl",
        PUBLIC / "evidence.jsonl",
        PUBLIC.parent / "manifest.json",
        PUBLIC.parent / "transport_manifest.json",
        RETRIEVAL_MANIFEST,
        GEN_META / "schema.json",
        GEN_META / "alias_registry.json",
        GEN_META / "parameter_registry.json",
        GEN_META / "test_generation_gold_aggregate.json",
        GEN_META / "materialized_artifact_hashes.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("missing required files: " + "; ".join(missing))

    qs = queries()
    materialized = read_json(GEN_META / "materialized_artifact_hashes.json")
    benchmark_root = PUBLIC.parent
    benchmark_manifest = read_json(benchmark_root / "manifest.json")
    transport_manifest = read_json(benchmark_root / "transport_manifest.json")
    for name in ("queries_test.jsonl", "evidence.jsonl"):
        expected = materialized.get(name)
        if (not isinstance(expected, str)
                or expected != benchmark_manifest["public_artifact_hashes"][f"public/{name}"]
                or expected != transport_manifest[f"public/{name}"]["uncompressed_sha256"]
                or sha256(PUBLIC / name) != expected):
            raise RuntimeError(f"materialized artifact hash missing or changed: {name}")
    qids = [query["query_id"] for query in qs]
    evidence = evidence_map()
    expected_hashes = expected_retrieval_hashes()
    if sha_text(json.dumps(qids, ensure_ascii=False, separators=(",", ":"))) != read_json(RETRIEVAL_MANIFEST)["query_ids_sha256"]:
        raise RuntimeError("test query IDs differ from sealed retrieval manifest")
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
            for problem in validate_selected_evidence_ids(query, row, evidence):
                problems.append(f"{method}/{query['query_id']}: {problem}")
    if problems:
        raise RuntimeError("preflight failed:\n- " + "\n- ".join(problems[:30]))

    aggregate = read_json(GEN_META / "test_generation_gold_aggregate.json")
    _, expected_index_hash = private_seal_hashes()
    result = {
        "status": "READY_FOR_GENERATION",
        "test_queries": 480,
        "methods": list(METHODS),
        "retrieval_prediction_hashes": expected_hashes,
        "materialized_artifact_hashes": materialized,
        "generation_schema_sha256": sha256(GEN_META / "schema.json"),
        "alias_registry_sha256": sha256(GEN_META / "alias_registry.json"),
        "parameter_registry_sha256": sha256(GEN_META / "parameter_registry.json"),
        "private_generation_gold_expected_sha256": aggregate["private_gold_sha256"],
        "private_generation_index_expected_sha256": expected_index_hash,
        "private_generation_gold_accessed": False,
        "prompt_version": PROMPT_VERSION,
        "protocol_version": GENERATION_PROTOCOL_VERSION,
        "model": MODEL,
        "temperature": TEMPERATURE,
    }
    write_json(OUT / "preflight.json", result)
    return result


def load_generation_rows(method: str) -> list[dict[str, Any]]:
    path = PRED_OUT / f"{method}.jsonl"
    return read_jsonl(path) if path.exists() else []


def ensure_clean_generation_restart(existing: dict[str, list[dict[str, Any]]], session: str) -> None:
    """Refuse to resume rows from a different formal session.

    Aborted predictions are retained for audit and must be archived outside the
    repository before a new formal session starts. They are never rewritten as
    rows for the new model/protocol session.
    """
    for method, rows in existing.items():
        mismatched = [
            index
            for index, row in enumerate(rows)
            if row.get("session_fingerprint") != session
        ]
        if mismatched:
            raise RuntimeError(
                f"{method}: resume session mismatch; existing rows belong to a different formal session "
                "and must be archived outside the repository before clean restart"
            )


def run_generation(methods: tuple[str, ...]) -> dict[str, Any]:
    if methods != METHODS:
        raise RuntimeError("formal generation requires --all five methods")
    if (OUT / "generation_prediction_manifest.json").exists():
        raise RuntimeError("generation predictions already frozen")
    pre = preflight()
    session = formal_session_fingerprint(pre)
    qs = queries()
    evidence = evidence_map()
    retrieval = retrieval_predictions()
    output_schema = schema()
    existing = {method: load_generation_rows(method) for method in methods}
    ensure_clean_generation_restart(existing, session)

    for method in methods:
        if len(existing[method]) > len(qs):
            raise RuntimeError(f"{method}: existing generation progress exceeds query count")
        if any(row.get("query_id") != qs[index]["query_id"] for index, row in enumerate(existing[method])):
            raise RuntimeError(f"{method}: existing generation progress query order mismatch")
        for index, row in enumerate(existing[method]):
            query = qs[index]
            selected_ids = list(retrieval[method][index]["selected_evidence_ids"])
            selected = [evidence[eid] for eid in selected_ids]
            if row.get("input_evidence_ids") != selected_ids or row.get("session_fingerprint") != session:
                raise RuntimeError(f"{method}/{query['query_id']}: resume session mismatch")
            system, user = build_prompt(query, selected, output_schema)
            if row.get("initial_request_fingerprint") != request_fingerprint(OFFICIAL_ENDPOINT, system, user):
                raise RuntimeError(f"{method}/{query['query_id']}: resume initial request mismatch")
            if row.get("repair_used"):
                initial = row.get("initial_generation")
                errors = validate_generation_output(initial, output_schema, set(selected_ids), query["asset_id"])
                if not errors or errors != row.get("initial_validation_errors"):
                    raise RuntimeError(f"{method}/{query['query_id']}: resume repair input mismatch")
                repair_system, repair_user = repair_prompt(query, selected, initial, errors, output_schema)
                repair_hash = request_fingerprint(OFFICIAL_ENDPOINT, repair_system, repair_user)
                if row.get("repair_request_fingerprint") != repair_hash:
                    raise RuntimeError(f"{method}/{query['query_id']}: resume repair request mismatch")
            elif row.get("repair_request_fingerprint") is not None:
                raise RuntimeError(f"{method}/{query['query_id']}: unexpected repair provenance")
    client = DeepSeekClient(CACHE / "api_cache", official=True)

    for index, query in enumerate(qs):
        for method in methods:
            if len(existing[method]) > index:
                continue
            retrieval_row = retrieval[method][index]
            selected_ids = list(retrieval_row["selected_evidence_ids"])
            selected = [evidence[evidence_id] for evidence_id in selected_ids]
            system, user = build_prompt(query, selected, output_schema)
            initial_hash = request_fingerprint(client.endpoint, system, user)
            initial = client.call(system, user, f"generate:{method}:{query['query_id']}")
            if client.last_request_hash != initial_hash:
                raise RuntimeError("initial request fingerprint differs from actual client payload")
            errors = validate_generation_output(initial, output_schema, set(selected_ids), query["asset_id"])
            initial_errors = errors
            repair_used = False
            repair_hash = None
            final = initial
            if errors:
                repair_used = True
                repair_system, repair_user = repair_prompt(query, selected, initial, errors, output_schema)
                repair_hash = request_fingerprint(client.endpoint, repair_system, repair_user)
                final = client.call(repair_system, repair_user, f"repair:{method}:{query['query_id']}")
                if client.last_request_hash != repair_hash:
                    raise RuntimeError("repair request fingerprint differs from actual client payload")
                errors = validate_generation_output(final, output_schema, set(selected_ids), query["asset_id"])
            row = {
                "query_id": query["query_id"],
                "input_evidence_ids": selected_ids,
                "generation": final,
                "repair_used": repair_used,
                "validation_errors": errors,
                "session_fingerprint": session,
                "initial_request_fingerprint": initial_hash,
                "repair_request_fingerprint": repair_hash,
                "initial_generation": initial if repair_used else None,
                "initial_validation_errors": initial_errors if repair_used else None,
                "request_provenance": {
                    "endpoint": client.endpoint,
                    "model": MODEL,
                    "prompt_sha256": sha_text(generator_instructions()),
                    "schema_sha256": sha256(GEN_META / "schema.json"),
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_TOKENS,
                },
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
        "protocol_version": GENERATION_PROTOCOL_VERSION,
        "client_stats": client.stats,
        "endpoint": client.endpoint,
        "model": MODEL,
        "prompt_sha256": sha_text(generator_instructions()),
        "schema_sha256": sha256(GEN_META / "schema.json"),
        "session_fingerprint": session,
        "unresolved": unresolved,
    }
    write_json(OUT / "generation_runtime.json", runtime)
    return runtime


def validate_generation_files(session: str) -> dict[str, str]:
    qs = queries()
    retrieval = retrieval_predictions()
    evidence = evidence_map()
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
            records = [evidence[eid] for eid in selected]
            validate_generation_row(row, query, selected, records, output_schema, session)
        hashes[method] = sha256(path)
    return hashes


def validate_generation_row(
    row: dict[str, Any],
    query: dict[str, Any],
    selected: list[str],
    records: list[dict[str, Any]],
    output_schema: dict[str, Any],
    session: str,
) -> list[str]:
    label = str(query.get("query_id", "unknown"))
    if row.get("session_fingerprint") != session:
        raise RuntimeError(f"{label}: formal session mismatch")
    system, user = build_prompt(query, records, output_schema)
    if row.get("initial_request_fingerprint") != request_fingerprint(OFFICIAL_ENDPOINT, system, user):
        raise RuntimeError(f"{label}: initial request fingerprint changed")
    if row.get("repair_used"):
        initial = row.get("initial_generation")
        initial_errors = validate_generation_output(initial, output_schema, set(selected), query["asset_id"])
        if not initial_errors or initial_errors != row.get("initial_validation_errors"):
            raise RuntimeError(f"{label}: repair input changed")
        repair_system, repair_user = repair_prompt(query, records, initial, initial_errors, output_schema)
        if row.get("repair_request_fingerprint") != request_fingerprint(OFFICIAL_ENDPOINT, repair_system, repair_user):
            raise RuntimeError(f"{label}: repair request fingerprint changed")
    elif row.get("repair_request_fingerprint") is not None:
        raise RuntimeError(f"{label}: unexpected repair fingerprint")
    if row.get("request_provenance") != {
        "endpoint": OFFICIAL_ENDPOINT,
        "model": MODEL,
        "prompt_sha256": sha_text(generator_instructions()),
        "schema_sha256": sha256(GEN_META / "schema.json"),
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }:
        raise RuntimeError(f"{label}: missing or changed request provenance")
    errors = validate_generation_output(row.get("generation"), output_schema, set(selected), query["asset_id"])
    if row.get("validation_errors") != errors:
        raise RuntimeError(f"{label}: validation error provenance changed")
    return errors


def freeze() -> dict[str, Any]:
    if (OUT / "generation_prediction_manifest.json").exists():
        raise RuntimeError("generation predictions already frozen")
    pre = preflight()
    session = formal_session_fingerprint(pre)
    hashes = validate_generation_files(session)
    runtime = read_json(OUT / "generation_runtime.json") if (OUT / "generation_runtime.json").exists() else {}
    if runtime.get("endpoint") != OFFICIAL_ENDPOINT or runtime.get("model") != MODEL or runtime.get("prompt_sha256") != sha_text(generator_instructions()) or runtime.get("schema_sha256") != pre["generation_schema_sha256"] or runtime.get("session_fingerprint") != session or runtime.get("methods") != list(METHODS):
        raise RuntimeError("formal generation runtime provenance missing or changed")
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
        "session_fingerprint": session,
        "retrieval_prediction_hashes": pre["retrieval_prediction_hashes"],
        "materialized_artifact_hashes": pre["materialized_artifact_hashes"],
        "generation_prediction_hashes": hashes,
        "schema_sha256": pre["generation_schema_sha256"],
        "alias_registry_sha256": pre["alias_registry_sha256"],
        "parameter_registry_sha256": pre["parameter_registry_sha256"],
        "prompt_sha256": sha_text(generator_instructions()),
        "scoring_fingerprint": scoring_fingerprint(),
        "request_config": {"max_tokens": MAX_TOKENS, "response_format": "json_object"},
        "private_generation_gold_expected_sha256": pre["private_generation_gold_expected_sha256"],
        "private_generation_index_expected_sha256": pre["private_generation_index_expected_sha256"],
        "private_generation_gold_accessed": False,
        "retrieval_relations_passed_to_generator": False,
        "method_identity_passed_to_generator": False,
        "runtime": runtime.get("client_stats", {}),
    }
    write_json(OUT / "generation_prediction_manifest.json", manifest)
    return manifest


def load_private_gold(root: Path) -> tuple[dict[str, dict[str, Any]], str, str]:
    gold_path = root / "gold_test.jsonl"
    index_path = root / "gold_test_index.jsonl"
    expected, index_expected = private_seal_hashes()
    if not gold_path.exists() or not index_path.exists():
        raise RuntimeError("private generation gold/index missing")
    actual = sha256(gold_path)
    if actual != expected:
        raise RuntimeError(f"private generation gold SHA mismatch: {actual}")
    actual_index = sha256(index_path)
    if actual_index != index_expected:
        raise RuntimeError("private gold index SHA mismatch")
    gold_rows = read_jsonl(gold_path)
    index_rows = read_jsonl(index_path)
    if len(gold_rows) != 240 or len(index_rows) != 240:
        raise RuntimeError("expected 240 semantic private gold objects")
    by_query: dict[str, dict[str, Any]] = {}
    seen_semantic_ids: set[str] = set()
    for gold, index in zip(gold_rows, index_rows):
        semantic_id = index.get("semantic_gold_id")
        if not isinstance(semantic_id, str) or not semantic_id or semantic_id in seen_semantic_ids:
            raise RuntimeError("duplicate private index semantic gold ID")
        seen_semantic_ids.add(semantic_id)
        for query_id in index.get("query_ids", []):
            if query_id in by_query:
                raise RuntimeError(f"duplicate private gold query id {query_id}")
            by_query[query_id] = gold
    if len(by_query) != 480:
        raise RuntimeError("private gold index must cover 480 query rows")
    return by_query, actual, actual_index


def private_seal_hashes() -> tuple[str, str]:
    metadata = read_json(GEN_META / "test_generation_gold_aggregate.json")
    expected = metadata["private_gold_sha256"]
    index_expected = metadata.get("private_index_sha256")
    if not isinstance(expected, str) or len(expected) != 64 or not isinstance(index_expected, str) or len(index_expected) != 64:
        raise RuntimeError("sealed public metadata lacks private_index_sha256; cannot safely pair private gold and index")
    return expected, index_expected


def validate_frozen_private_seal(manifest: dict[str, Any], preflight_result: dict[str, Any]) -> None:
    if manifest.get("private_generation_gold_expected_sha256") != preflight_result["private_generation_gold_expected_sha256"]:
        raise RuntimeError("frozen private gold expected SHA changed")
    if manifest.get("private_generation_index_expected_sha256") != preflight_result["private_generation_index_expected_sha256"]:
        raise RuntimeError("frozen private index expected SHA changed")


def ensure_private_output_outside_repo(private_root: Path) -> None:
    repo = ROOT.resolve()
    for path in (private_root, private_root / "evaluation_details_v1"):
        if path.resolve().is_relative_to(repo):
            raise RuntimeError("private evaluation output must be outside repository root")


def validate_private_gold_objects(by_query: dict[str, dict[str, Any]], output_schema: dict[str, Any], canon: Canonicalizer) -> None:
    seen_gold_ids: set[int] = set()
    for gold in by_query.values():
        if id(gold) in seen_gold_ids:
            continue
        seen_gold_ids.add(id(gold))
        gold_errors = validate_generation_output(gold, output_schema)
        if gold_errors:
            raise RuntimeError("private generation gold failed v1.3 schema/invariant validation: " + "; ".join(gold_errors[:10]))
        validate_gold_action_uniqueness(gold, canon)


def claim_formal_evaluation_once(start_path: Path, manifest_path: Path) -> None:
    start_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with os.fdopen(os.open(start_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as lock:
            json.dump({"status": "FORMAL_EVALUATION_STARTED", "timestamp_utc": datetime.now(timezone.utc).isoformat(), "generation_prediction_manifest_sha256": sha256(manifest_path)}, lock)
    except FileExistsError:
        raise RuntimeError("formal generation evaluation already started") from None


def evaluate(private_root: Path) -> dict[str, Any]:
    ensure_private_output_outside_repo(private_root)
    private_gold_path = private_root / "gold_test.jsonl"
    private_index_path = private_root / "gold_test_index.jsonl"
    if not private_gold_path.exists() or not private_index_path.exists():
        raise RuntimeError("private generation gold/index missing")
    start_path = OUT / "evaluation_started.json"
    if start_path.exists() or (OUT / "final_evaluation_manifest.json").exists() or (OUT / "metrics.json").exists():
        raise RuntimeError("formal generation evaluation already completed or artifacts exist")
    if (private_root / "evaluation_details_v1").exists():
        raise RuntimeError("private item-level evaluation artifacts already exist")
    manifest_path = OUT / "generation_prediction_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("freeze generation predictions before evaluation")
    manifest = read_json(manifest_path)
    if manifest.get("scoring_fingerprint") != scoring_fingerprint():
        raise RuntimeError("frozen evaluator/schema/registry/config changed")
    if manifest.get("prompt_sha256") != sha_text(generator_instructions()) or manifest.get("request_config") != {"max_tokens": MAX_TOKENS, "response_format": "json_object"}:
        raise RuntimeError("frozen prompt/request config changed")
    pre = preflight()
    validate_frozen_private_seal(manifest, pre)
    if pre["retrieval_prediction_hashes"] != manifest.get("retrieval_prediction_hashes") or pre["materialized_artifact_hashes"] != manifest.get("materialized_artifact_hashes"):
        raise RuntimeError("frozen retrieval or materialized benchmark inputs changed")
    session = formal_session_fingerprint(pre)
    if manifest.get("session_fingerprint") != session:
        raise RuntimeError("frozen formal session changed")
    current = validate_generation_files(session)
    if current != manifest["generation_prediction_hashes"]:
        raise RuntimeError("generation predictions changed after freeze")
    private_seal_hashes()
    claim_formal_evaluation_once(start_path, manifest_path)

    by_query, gold_hash, index_hash = load_private_gold(private_root)
    if gold_hash != manifest["private_generation_gold_expected_sha256"]:
        raise RuntimeError("private gold differs from frozen expectation")
    if index_hash != manifest["private_generation_index_expected_sha256"]:
        raise RuntimeError("private gold index differs from frozen expectation")

    qs = queries()
    retrieval = retrieval_predictions()
    output_schema = schema()
    canon = Canonicalizer(aliases(), parameters())
    validate_private_gold_objects(by_query, output_schema, canon)
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
        "private_generation_index_sha256": index_hash,
        "private_item_level_scores_written_outside_repo": True,
        "aggregate_metrics_path": str((OUT / "metrics.json").relative_to(ROOT)),
        "methods": list(METHODS),
        "query_count_per_method": 480,
        "evaluation_count": 1,
        "protocol_version": GENERATION_PROTOCOL_VERSION,
    }
    write_json(OUT / "final_evaluation_manifest.json", final)
    return metrics
