"""Freeze all gold-free v5 holdout retrieval outputs before evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/tef_v5_holdout_v3"
DATA_FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
INPUT = ROOT / "experiments/runs/ta_tg_input_v5_holdout_v1"
SHARED = ROOT / "experiments/runs/tef_v5_holdout_shared_v1"
TA = ROOT / "experiments/runs/ta_rag_v5_holdout_v1"
TG = ROOT / "experiments/runs/tg_rag_v5_holdout_v1"
OUT = ROOT / "experiments/analyses/tef_v5_holdout_retrieval_freeze_v1"
TOP_K = 5


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def verify_hashes(hashes: dict[str, str], base: Path = ROOT) -> None:
    for name, expected in hashes.items():
        path = base / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"hash mismatch: {path}")


def main() -> None:
    dataset_freeze = read(DATA_FREEZE)
    if dataset_freeze["status"] != "self_generated_holdout_frozen_without_independent_review":
        raise RuntimeError("unexpected dataset freeze status")
    if dataset_freeze["ranking_run_before_freeze"]:
        raise RuntimeError("dataset was ranked before freeze")
    public_hashes = {
        name: digest
        for name, digest in dataset_freeze["hashes"].items()
        if "\\authoring\\" not in name and "\\evaluation\\" not in name
    }
    verify_hashes(public_hashes)

    queries = {row["query_id"]: row for row in lines(DATA / "queries.jsonl")}
    snapshots = read(INPUT / "snapshot_mapping.json")
    snapshot_for = {(row["asset_id"], row["query_time"]): key for key, row in snapshots.items()}
    if len(queries) != 16 or len(snapshots) != 8 or len(snapshot_for) != 8:
        raise RuntimeError("unexpected query or snapshot cardinality")

    manifests = {
        "shared": SHARED / "retrieval_complete.json",
        "ta": TA / "completion.json",
        "tg": TG / "completion.json",
    }
    completions = {name: read(path) for name, path in manifests.items()}
    if any(row.get("gold_read") is not False for row in completions.values()):
        raise RuntimeError("retrieval was not gold-free")
    if any(row.get("queries") != 16 for row in completions.values()):
        raise RuntimeError("retrieval query count is incomplete")

    verify_hashes(completions["shared"]["query_output_hashes"], SHARED / "queries")
    verify_hashes(completions["ta"]["query_output_hashes"], TA / "queries")

    output_hashes: dict[str, str] = {rel(path): sha(path) for path in manifests.values()}
    returned_counts: dict[str, list[int]] = {"shared": [], "ta": [], "tg": []}
    for query_id, query in sorted(queries.items()):
        snapshot_key = snapshot_for[(query["asset_id"], query["query_time"])]
        visible = set(snapshots[snapshot_key]["visible_record_ids"])

        shared_path = SHARED / "queries" / f"{query_id}.json"
        shared = read(shared_path)
        if set(shared["candidate_ids"]) != visible or shared["candidate_count"] != len(visible):
            raise RuntimeError(f"shared candidate mismatch: {query_id}")
        for method in ("scoped_hybrid", "scoped_latest", "tef_v5"):
            ids = shared["methods"][method]["evidence_ids"]
            if len(ids) != TOP_K or len(ids) != len(set(ids)) or set(ids) - visible:
                raise RuntimeError(f"invalid shared output: {query_id}/{method}")
        returned_counts["shared"].append(TOP_K)
        output_hashes[rel(shared_path)] = sha(shared_path)

        ta_path = TA / "queries" / f"{query_id}.json"
        ta = read(ta_path)
        ids = ta["evidence_ids"]
        if ta["snapshot_key"] != snapshot_key or ta["candidate_count"] != len(visible):
            raise RuntimeError(f"TA candidate mismatch: {query_id}")
        if len(ids) != TOP_K or len(ids) != len(set(ids)) or set(ids) - visible:
            raise RuntimeError(f"invalid TA output: {query_id}")
        returned_counts["ta"].append(len(ids))
        output_hashes[rel(ta_path)] = sha(ta_path)

    for snapshot_key, expected in completions["tg"]["snapshot_completion_hashes"].items():
        snapshot_dir = TG / "snapshots" / snapshot_key
        completion_path = snapshot_dir / "completion.json"
        if sha(completion_path) != expected:
            raise RuntimeError(f"TG completion changed: {snapshot_key}")
        completion = read(completion_path)
        verify_hashes(completion["query_output_hashes"], snapshot_dir / "queries")
        output_hashes[rel(completion_path)] = sha(completion_path)
        visible = set(snapshots[snapshot_key]["visible_record_ids"])
        for query_path in sorted((snapshot_dir / "queries").glob("*.json")):
            row = read(query_path)
            ids = row["evidence_ids"]
            if row["candidate_count"] != len(visible) or len(ids) > TOP_K:
                raise RuntimeError(f"TG candidate/Top-k mismatch: {row['query_id']}")
            if len(ids) != len(set(ids)) or set(ids) - visible:
                raise RuntimeError(f"invalid TG output: {row['query_id']}")
            returned_counts["tg"].append(len(ids))
            output_hashes[rel(query_path)] = sha(query_path)

    if len(returned_counts["tg"]) != 16:
        raise RuntimeError("TG query output matrix is incomplete")
    tg_failed = sorted(
        read(path)["query_id"]
        for path in TG.glob("snapshots/*/queries/*.json")
        if len(read(path)["evidence_ids"]) == 0
    )
    expected_failed = [
        "tefv5h-q-03-02",
        "tefv5h-q-04-00",
        "tefv5h-q-04-01",
        "tefv5h-q-04-02",
        "tefv5h-q-04-03",
    ]
    if tg_failed != expected_failed:
        raise RuntimeError(f"unexpected TG failure set: {tg_failed}")

    OUT.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "retrieval_outputs_frozen_before_gold_scoring",
        "dataset": "tef_v5_holdout_v3",
        "dataset_review_status": "self_generated_frozen_without_independent_review",
        "queries": 16,
        "top_k": TOP_K,
        "valid_primary_methods": [
            "scoped_hybrid",
            "scoped_latest",
            "tef_v5",
            "ta_rag_no_event_interval_compat",
        ],
        "diagnostic_only_methods": {
            "tg_rag_official_compat": {
                "status": "invalid_external_failure",
                "cause_observed_during_run": "provider_http_402_insufficient_balance",
                "failed_query_ids": expected_failed,
                "full_top5_queries": sum(count == TOP_K for count in returned_counts["tg"]),
                "zero_result_queries": sum(count == 0 for count in returned_counts["tg"]),
            }
        },
        "shared_candidate_counts": sorted({row["candidate_count"] for row in snapshots.values()}),
        "gold_read": False,
        "authoring_read": False,
        "output_hashes": dict(sorted(output_hashes.items())),
        "input_hashes": {
            rel(Path(__file__).resolve()): sha(Path(__file__).resolve()),
            rel(DATA_FREEZE): sha(DATA_FREEZE),
            rel(INPUT / "snapshot_mapping.json"): sha(INPUT / "snapshot_mapping.json"),
            rel(ROOT / "plans/TEF_RAG_v5_holdout_v3_TG外部失败处置.md"): sha(
                ROOT / "plans/TEF_RAG_v5_holdout_v3_TG外部失败处置.md"
            ),
        },
    }
    (OUT / "retrieval_freeze_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": manifest["status"],
        "outputs": len(output_hashes),
        "valid_primary_methods": len(manifest["valid_primary_methods"]),
        "tg_failed_queries": len(expected_failed),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
