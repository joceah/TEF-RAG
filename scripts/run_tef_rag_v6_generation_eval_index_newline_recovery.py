"""One-shot recovery for the audited Windows CRLF private index artifact.

This module deliberately lives outside the frozen evaluation CLI.  It accepts
one known transport representation (the exact LF-to-CRLF rendering proven by
the failed v1.9 evaluation) and reuses the frozen scoring functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.reconstruct_tef_v6_generation_private_index import (
    reconstruct_index_bytes,
    reconstruct_index_rows,
)
from tef_rag_v6 import generation_eval_cli as cli
from tef_rag_v6.generation_eval import Canonicalizer


RECOVERY_PROTOCOL_VERSION = "private-index-crlf-recovery-v1"
EXPECTED_MANIFEST_SHA256 = "b5d586d4f64b06bef9279b27a727939980d08582c75ed9340f3a50e05a626f1b"
EXPECTED_PRIVATE_INDEX_RAW_SHA256 = "5904d4b4e65bafa9c0accef2a66fb4c3d96ea29b2cbfdc6b7b9e6002675511d6"
RECOVERY_LOCK_NAME = "evaluation_recovery_crlf_v1_started.json"
RECOVERY_METRICS_NAME = "metrics_recovery_crlf_v1.json"
RECOVERY_MANIFEST_NAME = "final_evaluation_recovery_crlf_v1_manifest.json"
RECOVERY_DETAILS_NAME = "evaluation_details_v1_recovery_crlf"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _first_diff(left: bytes, right: bytes) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right)) if len(left) != len(right) else None


def validate_exact_crlf_transport(
    actual: bytes,
    canonical: bytes,
    *,
    expected_raw_sha256: str,
    expected_rows: int,
) -> dict[str, Any]:
    """Accept only the exact audited LF-to-CRLF byte transformation."""
    if sha_bytes(actual) != expected_raw_sha256:
        raise RuntimeError("private index raw SHA mismatch")
    if actual != canonical.replace(b"\n", b"\r\n"):
        raise RuntimeError("private index is not the exact LF-to-CRLF transport variant")
    canonical_lf = canonical.count(b"\n")
    actual_crlf = actual.count(b"\r\n")
    if canonical_lf != expected_rows or actual_crlf != expected_rows:
        raise RuntimeError("private index newline row count mismatch")
    if actual.count(b"\n") != actual_crlf or actual.count(b"\r") != actual_crlf:
        raise RuntimeError("private index contains lone newline bytes")
    if actual.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError("private index contains a UTF-8 BOM")
    if not canonical.endswith(b"\n") or not actual.endswith(b"\r\n"):
        raise RuntimeError("private index must have a final newline")
    return {
        "canonical_expected_index_sha256": sha_bytes(canonical),
        "actual_private_index_raw_sha256": sha_bytes(actual),
        "transport_equivalence": "exact_lf_to_crlf",
        "canonical_row_count": canonical_lf,
        "actual_crlf_count": actual_crlf,
        "actual_has_lone_lf": False,
        "actual_has_lone_cr": False,
        "actual_has_bom": False,
        "canonical_has_final_lf": True,
        "actual_has_final_crlf": True,
        "first_diff_against_canonical": _first_diff(actual, canonical),
    }


def validate_index_semantics(
    actual_rows: list[dict[str, Any]],
    reconstructed_rows: list[dict[str, Any]],
    *,
    expected_rows: int,
    expected_query_coverage: int,
) -> dict[str, Any]:
    """Require exact row, order, field, ID, and query coverage equality."""
    if len(actual_rows) != expected_rows or len(reconstructed_rows) != expected_rows:
        raise RuntimeError("private index must contain exactly 240 rows")
    actual_ids = [row.get("semantic_gold_id") for row in actual_rows]
    if any(not isinstance(value, str) or not value for value in actual_ids):
        raise RuntimeError("private index semantic_gold_id is malformed")
    if len(set(actual_ids)) != len(actual_ids):
        raise RuntimeError("duplicate private index semantic_gold_id")
    query_ids: list[str] = []
    for row in actual_rows:
        ids = row.get("query_ids")
        if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
            raise RuntimeError("private index query_ids is malformed")
        query_ids.extend(ids)
    if len(query_ids) != expected_query_coverage or len(set(query_ids)) != expected_query_coverage:
        raise RuntimeError("private index query coverage must contain 480 unique query IDs")
    if actual_rows != reconstructed_rows:
        raise RuntimeError("private index parsed rows differ from public reconstruction")
    return {
        "private_index_parsed_equals_public_reconstruction": True,
        "private_index_row_count": len(actual_rows),
        "query_coverage": len(query_ids),
    }


def _pair_private_rows(
    gold_rows: list[dict[str, Any]],
    index_rows: list[dict[str, Any]],
    *,
    expected_rows: int = 240,
    expected_query_coverage: int = 480,
) -> dict[str, dict[str, Any]]:
    if len(gold_rows) != expected_rows or len(index_rows) != expected_rows:
        raise RuntimeError("expected 240 semantic private gold objects")
    by_query: dict[str, dict[str, Any]] = {}
    seen_semantic: set[str] = set()
    for gold, index in zip(gold_rows, index_rows):
        semantic_id = index.get("semantic_gold_id")
        if not isinstance(semantic_id, str) or not semantic_id or semantic_id in seen_semantic:
            raise RuntimeError("duplicate private index semantic gold ID")
        seen_semantic.add(semantic_id)
        query_ids = index.get("query_ids")
        if not isinstance(query_ids, list):
            raise RuntimeError("private index query_ids is malformed")
        for query_id in query_ids:
            if not isinstance(query_id, str) or query_id in by_query:
                raise RuntimeError("duplicate private gold query id")
            by_query[query_id] = gold
    if len(by_query) != expected_query_coverage:
        raise RuntimeError("private gold index must cover 480 query rows")
    return by_query


def _read_private_after_lock(
    private_root: Path,
    state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], str, str, dict[str, Any]]:
    gold_path = private_root / "gold_test.jsonl"
    index_path = private_root / "gold_test_index.jsonl"
    gold_bytes = gold_path.read_bytes()
    actual_gold_sha = sha_bytes(gold_bytes)
    if actual_gold_sha != state["expected_gold_sha256"]:
        raise RuntimeError("private gold SHA mismatch")
    actual_index_bytes = index_path.read_bytes()
    index_gate = validate_exact_crlf_transport(
        actual_index_bytes,
        state["reconstructed_index_bytes"],
        expected_raw_sha256=EXPECTED_PRIVATE_INDEX_RAW_SHA256,
        expected_rows=240,
    )
    index_text = actual_index_bytes.decode("utf-8-sig")
    index_rows = [json.loads(line) for line in index_text.splitlines() if line.strip()]
    reconstructed_rows = state["reconstructed_index_rows"]
    index_gate.update(validate_index_semantics(index_rows, reconstructed_rows, expected_rows=240, expected_query_coverage=480))
    gold_rows = cli.read_jsonl(gold_path)
    by_query = _pair_private_rows(gold_rows, index_rows)
    cli.validate_private_gold_objects(by_query, cli.schema(), Canonicalizer(cli.aliases(), cli.parameters()))
    return by_query, actual_gold_sha, index_gate["actual_private_index_raw_sha256"], index_gate


def _atomic_recovery_lock(path: Path, *, manifest_sha256: str, original_lock_sha256: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "FORMAL_EVALUATION_RECOVERY_STARTED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "recovery_protocol_version": RECOVERY_PROTOCOL_VERSION,
        "generation_prediction_manifest_sha256": manifest_sha256,
        "original_evaluation_lock_sha256": original_lock_sha256,
    }
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
    except FileExistsError:
        raise RuntimeError("private index CRLF recovery already started") from None


def public_prechecks(private_root: Path) -> dict[str, Any]:
    """Run all checks that are allowed before private bytes are read."""
    private_root = private_root.resolve()
    cli.ensure_private_output_outside_repo(private_root)
    out = cli.OUT
    manifest_path = out / "generation_prediction_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("freeze generation predictions before recovery")
    manifest_sha = cli.sha256(manifest_path)
    if manifest_sha != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("frozen generation manifest SHA mismatch")
    manifest = cli.read_json(manifest_path)
    if manifest.get("private_generation_gold_accessed") is not False:
        raise RuntimeError("frozen manifest already accessed private generation gold")
    original_lock = out / "evaluation_started.json"
    if not original_lock.exists():
        raise RuntimeError("original evaluation lock is missing")
    original_lock_data = cli.read_json(original_lock)
    if original_lock_data.get("status") != "FORMAL_EVALUATION_STARTED" or original_lock_data.get("generation_prediction_manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("original evaluation lock is not the expected failed attempt")
    for path in (out / "metrics.json", out / "final_evaluation_manifest.json", private_root / "evaluation_details_v1"):
        if path.exists():
            raise RuntimeError(f"original evaluation output already exists: {path}")
    recovery_lock = out / RECOVERY_LOCK_NAME
    for path in (recovery_lock, out / RECOVERY_METRICS_NAME, out / RECOVERY_MANIFEST_NAME, private_root / RECOVERY_DETAILS_NAME):
        if path.exists():
            raise RuntimeError(f"recovery artifact already exists: {path}")
    if manifest.get("scoring_fingerprint") != cli.scoring_fingerprint():
        raise RuntimeError("frozen evaluator/schema/registry/config changed")
    pre = cli.preflight()
    cli.validate_frozen_private_seal(manifest, pre)
    if pre["retrieval_prediction_hashes"] != manifest.get("retrieval_prediction_hashes") or pre["materialized_artifact_hashes"] != manifest.get("materialized_artifact_hashes"):
        raise RuntimeError("frozen retrieval or materialized benchmark inputs changed")
    session = cli.formal_session_fingerprint(pre)
    current_hashes = cli.validate_generation_files(session)
    if current_hashes != manifest.get("generation_prediction_hashes"):
        raise RuntimeError("generation predictions changed after freeze")
    reconstructed_bytes = reconstruct_index_bytes()
    reconstructed_rows = reconstruct_index_rows()
    expected_index_sha = manifest.get("private_generation_index_expected_sha256")
    if sha_bytes(reconstructed_bytes) != expected_index_sha:
        raise RuntimeError("public reconstruction does not match frozen private index SHA")
    expected_gold_sha = manifest.get("private_generation_gold_expected_sha256")
    if not isinstance(expected_gold_sha, str) or len(expected_gold_sha) != 64:
        raise RuntimeError("frozen private gold expected SHA is malformed")
    if not (private_root / "gold_test.jsonl").exists() or not (private_root / "gold_test_index.jsonl").exists():
        raise RuntimeError("private generation gold/index missing")
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "original_lock": original_lock,
        "original_lock_sha256": cli.sha256(original_lock),
        "expected_gold_sha256": expected_gold_sha,
        "expected_index_sha256": expected_index_sha,
        "session": session,
        "prediction_hashes": current_hashes,
        "scoring_fingerprint": cli.scoring_fingerprint(),
        "reconstructed_index_bytes": reconstructed_bytes,
        "reconstructed_index_rows": reconstructed_rows,
        "private_root": private_root,
        "recovery_lock": recovery_lock,
        "protocol_path": cli.ROOT / "plans/TEF_RAG_v6_generation_evaluation_recovery_v1_private_index_crlf.md",
    }


def _score_and_write(state: dict[str, Any], by_query: dict[str, dict[str, Any]], gold_sha: str, index_sha: str, index_gate: dict[str, Any]) -> dict[str, Any]:
    out = cli.OUT
    qs = cli.queries()
    retrieval = cli.retrieval_predictions()
    output_schema = cli.schema()
    canon = Canonicalizer(cli.aliases(), cli.parameters())
    metrics: dict[str, Any] = {}
    detail_rows: dict[str, list[dict[str, Any]]] = {}
    for method in cli.METHODS:
        rows = cli.read_jsonl(cli.PRED_OUT / f"{method}.jsonl")
        scored: list[dict[str, Any]] = []
        for index, (query, row) in enumerate(zip(qs, rows)):
            gold = by_query[query["query_id"]]
            values = cli.evaluate_generation_prediction(
                row["generation"], gold, output_schema, canon,
                set(retrieval[method][index]["selected_evidence_ids"]), query["asset_id"],
            )
            scored.append({"query_id": query["query_id"], **values})
        detail_rows[method] = scored
        metrics[method] = cli.macro_average([{key: value for key, value in row.items() if key != "query_id"} for row in scored])
    details = state["private_root"] / RECOVERY_DETAILS_NAME
    details.mkdir(parents=True, exist_ok=True)
    for method, rows in detail_rows.items():
        cli.write_jsonl(details / f"{method}.jsonl", rows)
    metrics_path = out / RECOVERY_METRICS_NAME
    cli.write_json(metrics_path, metrics)
    protocol_path = state["protocol_path"]
    final = {
        "status": "GENERATION_EVALUATION_COMPLETE_VIA_AUDITED_PRIVATE_INDEX_CRLF_RECOVERY",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "generation_protocol_version": cli.GENERATION_PROTOCOL_VERSION,
        "recovery_protocol_version": RECOVERY_PROTOCOL_VERSION,
        "original_evaluation_attempt": {
            "status": "FAILED_PRE_SCORING_PRIVATE_INDEX_RAW_SEAL",
            "evaluation_started_sha256": state["original_lock_sha256"],
            "generation_prediction_manifest_sha256": state["manifest_sha256"],
            "expected_private_index_sha256": state["expected_index_sha256"],
            "observed_private_index_sha256": index_sha,
        },
        "recovery_attempt_count": 1,
        "scoring_evaluation_count": 1,
        "generation_prediction_manifest_sha256": state["manifest_sha256"],
        "generation_prediction_hashes": state["prediction_hashes"],
        "original_scoring_fingerprint": state["scoring_fingerprint"],
        "current_scoring_fingerprint": cli.scoring_fingerprint(),
        "private_generation_gold_sha256": gold_sha,
        "private_index_canonical_expected_sha256": state["expected_index_sha256"],
        "private_index_actual_raw_sha256": index_sha,
        "private_index_transport_equivalence": index_gate["transport_equivalence"],
        "private_index_parsed_equals_public_reconstruction": True,
        "private_index_row_count": index_gate["private_index_row_count"],
        "query_coverage": index_gate["query_coverage"],
        "private_item_level_scores_written_outside_repo": True,
        "metrics_path": str(metrics_path.relative_to(cli.ROOT)),
        "recovery_script_sha256": cli.sha256(Path(__file__).resolve()),
        "recovery_protocol_sha256": cli.sha256(protocol_path),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    cli.write_json(out / RECOVERY_MANIFEST_NAME, final)
    return metrics


def recover(private_root: Path) -> dict[str, Any]:
    state = public_prechecks(private_root)
    _atomic_recovery_lock(state["recovery_lock"], manifest_sha256=state["manifest_sha256"], original_lock_sha256=state["original_lock_sha256"])
    by_query, gold_sha, index_sha, index_gate = _read_private_after_lock(state["private_root"], state)
    return _score_and_write(state, by_query, gold_sha, index_sha, index_gate)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("recover")
    command.add_argument("--private-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "recover":
        print(json.dumps(recover(args.private_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
