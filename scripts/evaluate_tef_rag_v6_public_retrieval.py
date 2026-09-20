"""Fail-closed public evaluator for the released V6 retrieval test split.

The evaluator is deliberately a thin adapter around the frozen metric
implementation.  It validates the public test evaluator, query coverage,
prediction provenance, evidence identity, and temporal visibility before any
score is computed.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from tef_rag_v6.evaluation import average, evaluate_prediction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1"
DEFAULT_EVALUATOR = DEFAULT_BENCHMARK / "public/test_evaluator.jsonl"
DEFAULT_QUERIES = DEFAULT_BENCHMARK / "public/queries_test.jsonl"
DEFAULT_EVIDENCE = DEFAULT_BENCHMARK / "public/evidence.jsonl"
DEFAULT_PREDICTIONS = ROOT / "data/retrieval/frozen_test_predictions"
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")
TEST_EVALUATOR_SHA256 = "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"
PREDICTION_MANIFEST_SHA256 = "995b9f739ad85f77f54977f357714438d9b425e76a5fea07b9022b767185ab7f"
PREDICTION_SHA256S = {
    "bm25": "e3fda5e21a2a43a1a7411fcdfd5e793c23b8da2474e78506f8257e1998ec681e",
    "bge_reranker": "a26acd912729a1a2aeff14c8334e78d4f84826cb19f5d22f5e22287fa8089c9a",
    "temporal_bm25": "9dee0253619896e50e2f6d7e74209b70733090366d816347702a5820912b7ba9",
    "ta_rag": "c35b66edfc94e0ea901368be899b77850af34cfd23ee9027423e5452b103fcc8",
    "tef_rag_stage3d": "b7d02bf95cdbe522a667e7e7772ec72f3925761f76157c3fa3c421896c383e76",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(value)
    return rows


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label}: timestamp must be a string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}: invalid timestamp {value!r}") from exc


def load_test_evaluator(
    evaluator_path: Path = DEFAULT_EVALUATOR,
    queries_path: Path = DEFAULT_QUERIES,
) -> tuple[dict[str, dict[str, Any]], list[str], str]:
    raw = evaluator_path.read_bytes()
    digest = _sha256_bytes(raw)
    if digest != TEST_EVALUATOR_SHA256:
        raise ValueError(f"test evaluator SHA mismatch: {digest}")
    rows = _jsonl(evaluator_path)
    queries = _jsonl(queries_path)
    expected_ids = [row.get("query_id") for row in queries]
    if len(expected_ids) != 480 or any(not isinstance(value, str) for value in expected_ids):
        raise ValueError("queries_test.jsonl must contain exactly 480 string query IDs")
    if len(set(expected_ids)) != 480:
        raise ValueError("queries_test.jsonl contains duplicate query IDs")
    if len(rows) != 480:
        raise ValueError("test evaluator must contain exactly 480 rows")
    actual_ids: list[str] = []
    gold_by_query: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        query = row.get("query")
        gold = row.get("gold")
        if not isinstance(query, dict) or not isinstance(gold, dict):
            raise ValueError(f"test evaluator row {index + 1}: query/gold must be objects")
        query_id = query.get("query_id")
        if not isinstance(query_id, str):
            raise ValueError(f"test evaluator row {index + 1}: query_id must be a string")
        actual_ids.append(query_id)
        if query_id in gold_by_query:
            raise ValueError(f"duplicate test evaluator query_id: {query_id}")
        if not isinstance(gold.get("required_groups"), list) or not isinstance(gold.get("required_flow_edges"), list):
            raise ValueError(f"test evaluator row {index + 1}: malformed gold structure")
        gold_by_query[query_id] = gold
    if actual_ids != expected_ids:
        raise ValueError("test evaluator query IDs/order do not exactly match queries_test.jsonl")
    return gold_by_query, expected_ids, digest


def _load_public_inputs(
    queries_path: Path,
    evidence_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    queries = _jsonl(queries_path)
    query_by_id = {row["query_id"]: row for row in queries if isinstance(row.get("query_id"), str)}
    if len(query_by_id) != len(queries):
        raise ValueError("public test queries contain duplicate or malformed query IDs")
    evidence_rows = _jsonl(evidence_path)
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        evidence_id = row.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id in evidence_by_id:
            raise ValueError("public evidence IDs must be unique strings")
        evidence_by_id[evidence_id] = row
    return query_by_id, evidence_by_id


def _visible(evidence: dict[str, Any], query: dict[str, Any]) -> bool:
    if evidence.get("asset_id") != query.get("asset_id"):
        return False
    query_time = _parse_time(query.get("query_time"), "query_time")
    return (
        _parse_time(evidence.get("event_time"), "event_time") <= query_time
        and _parse_time(evidence.get("available_at"), "available_at") <= query_time
    )


def load_prediction_rows(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid prediction JSON: {path}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"prediction file must be a JSON array of objects: {path}")
    return value, _sha256_bytes(raw)


def validate_prediction_rows(
    method: str,
    rows: list[dict[str, Any]],
    expected_ids: list[str],
    query_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    if len(rows) != 480:
        raise ValueError(f"{method}: expected exactly 480 prediction rows")
    row_ids = [row.get("query_id") for row in rows]
    if any(not isinstance(value, str) for value in row_ids) or row_ids != expected_ids or len(set(row_ids)) != 480:
        raise ValueError(f"{method}: prediction query coverage/order mismatch")
    allowed_keys = {"query_id", "selected_evidence_ids", "relations", "uncertainty"}
    for index, row in enumerate(rows):
        query_id = row["query_id"]
        if set(row) - allowed_keys:
            raise ValueError(f"{method}/{query_id}: unexpected prediction fields")
        selected = row.get("selected_evidence_ids")
        if not isinstance(selected, list):
            raise ValueError(f"{method}/{query_id}: selected_evidence_ids must be a list")
        if len(selected) > 5:
            raise ValueError(f"{method}/{query_id}: selected_evidence_ids exceeds 5")
        if any(not isinstance(value, str) for value in selected):
            raise ValueError(f"{method}/{query_id}: evidence IDs must be strings")
        if len(selected) != len(set(selected)):
            raise ValueError(f"{method}/{query_id}: duplicate evidence IDs")
        query = query_by_id[query_id]
        for evidence_id in selected:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise ValueError(f"{method}/{query_id}: unknown evidence ID {evidence_id}")
            if not _visible(evidence, query):
                raise ValueError(f"{method}/{query_id}: evidence is not visible at query cutoff: {evidence_id}")


def _score_fingerprint(scores: list[dict[str, float]]) -> str:
    canonical = "\n".join(json.dumps(score, sort_keys=True, separators=(",", ":")) for score in scores)
    return _sha256_bytes(canonical.encode("utf-8"))


def validate_prediction_manifest(predictions_dir: Path) -> None:
    path = predictions_dir / "prediction_manifest.json"
    raw = path.read_bytes()
    digest = _sha256_bytes(raw)
    if digest != PREDICTION_MANIFEST_SHA256:
        raise ValueError(f"prediction manifest SHA mismatch: {digest}")
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("test_query_count") != 480 or manifest.get("sealed_evaluator_accessed") is not False:
        raise ValueError("prediction manifest integrity fields mismatch")
    for method in METHODS:
        entry = manifest.get("predictions", {}).get(method, {})
        if entry.get("query_count") != 480 or entry.get("prediction_sha256") != PREDICTION_SHA256S[method]:
            raise ValueError(f"prediction manifest mismatch for {method}")


def evaluate_all(
    predictions_dir: Path = DEFAULT_PREDICTIONS,
    evaluator_path: Path = DEFAULT_EVALUATOR,
    queries_path: Path = DEFAULT_QUERIES,
    evidence_path: Path = DEFAULT_EVIDENCE,
    require_manifest: bool = True,
) -> dict[str, Any]:
    if require_manifest:
        validate_prediction_manifest(predictions_dir)
    gold_by_query, expected_ids, evaluator_sha = load_test_evaluator(evaluator_path, queries_path)
    query_by_id, evidence_by_id = _load_public_inputs(queries_path, evidence_path)
    if list(query_by_id) != expected_ids:
        raise ValueError("public test query order differs from evaluator order")
    metrics: dict[str, dict[str, float | None]] = {}
    fingerprints: dict[str, str] = {}
    prediction_hashes: dict[str, str] = {}
    for method in METHODS:
        rows, prediction_sha = load_prediction_rows(predictions_dir / f"{method}.json")
        if require_manifest and prediction_sha != PREDICTION_SHA256S[method]:
            raise ValueError(f"{method}: prediction SHA mismatch: {prediction_sha}")
        validate_prediction_rows(method, rows, expected_ids, query_by_id, evidence_by_id)
        scores = [evaluate_prediction(row, gold_by_query[row["query_id"]], 5) for row in rows]
        aggregate = average(scores)
        if method != "tef_rag_stage3d":
            aggregate["edge_recall"] = None
        metrics[method] = aggregate
        fingerprints[method] = _score_fingerprint(scores)
        prediction_hashes[method] = prediction_sha
    return {
        "test_evaluator_sha256": evaluator_sha,
        "prediction_manifest_sha256": PREDICTION_MANIFEST_SHA256,
        "prediction_sha256s": prediction_hashes,
        "metrics": metrics,
        "score_fingerprints": fingerprints,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--evaluator", type=Path, default=DEFAULT_EVALUATOR)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    print(json.dumps(evaluate_all(args.predictions, args.evaluator, args.queries, args.evidence), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
