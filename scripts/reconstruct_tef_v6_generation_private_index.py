"""Reconstruct the sealed test index bytes from tracked public benchmark inputs.

This utility never reads or writes private gold. It consumes only committed
base64+xz transport parts and reproduces the generation-gold builder's index
row ordering and JSONL serialization.
"""
from __future__ import annotations

import base64
import hashlib
import json
import lzma
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _public_jsonl(transport: dict[str, Any], logical_name: str) -> list[dict[str, Any]]:
    record = transport[f"public/{logical_name}"]
    compressed_parts: list[bytes] = []
    for part in record["parts"]:
        raw = base64.b64decode((ROOT / part["repo_path"]).read_text(encoding="ascii"))
        if _sha(raw) != part["sha256"]:
            raise RuntimeError(f"transport part hash mismatch: {part['repo_path']}")
        compressed_parts.append(raw)
    compressed = b"".join(compressed_parts)
    if _sha(compressed) != record["compressed_sha256"]:
        raise RuntimeError(f"compressed transport hash mismatch: public/{logical_name}")
    data = lzma.decompress(compressed)
    if _sha(data) != record["uncompressed_sha256"]:
        raise RuntimeError(f"uncompressed transport hash mismatch: public/{logical_name}")
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def _visible_evidence(query: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = _parse_time(query["query_time"])
    rows: list[dict[str, Any]] = []
    for item in evidence:
        if item.get("split") != query["split"] or item.get("chain_id") != query["chain_id"]:
            continue
        if item.get("asset_id") != query.get("asset_id"):
            continue
        if _parse_time(item["event_time"]) > cutoff or _parse_time(item["available_at"]) > cutoff:
            continue
        is_proc = item.get("event_type") == "procedure_applicability" or item.get("source_type") == "procedure"
        if is_proc:
            if item.get("valid_from") and cutoff < _parse_time(item["valid_from"]):
                continue
            if item.get("valid_to") and cutoff >= _parse_time(item["valid_to"]):
                continue
            if item.get("withdrawn_at") and cutoff >= _parse_time(item["withdrawn_at"]):
                continue
            scope = item.get("model_scope") or []
            scope = [scope] if isinstance(scope, str) else scope
            if scope and query.get("asset_model") not in scope:
                continue
        rows.append(item)
    return sorted(rows, key=lambda row: (row["event_time"], row["available_at"], row["evidence_id"]))


def reconstruct_index_rows() -> list[dict[str, Any]]:
    transport = json.loads((BENCHMARK / "transport_manifest.json").read_text(encoding="utf-8"))
    chains = {row["chain_id"]: row for row in _public_jsonl(transport, "chains_test.jsonl")}
    queries = [row for row in _public_jsonl(transport, "queries_test.jsonl") if row.get("split") == "test"]
    evidence = _public_jsonl(transport, "evidence.jsonl")
    by_chain: dict[str, list[dict[str, Any]]] = {}
    for query in queries:
        by_chain.setdefault(query["chain_id"], []).append(query)

    rows: list[dict[str, Any]] = []
    for chain_id in sorted(chains):
        by_intent: dict[str, list[dict[str, Any]]] = {}
        for query in by_chain.get(chain_id, []):
            by_intent.setdefault(query["intent_id"], []).append(query)
        if len(by_intent) != 3 or any(len(items) != 2 for items in by_intent.values()):
            raise RuntimeError(f"test/{chain_id}: expected 3 intents x 2 paraphrases")
        for intent_id in sorted(by_intent):
            pair = sorted(by_intent[intent_id], key=lambda row: (row.get("paraphrase_id", 0), row["query_id"]))
            visible = [_visible_evidence(query, evidence) for query in pair]
            common_ids = set(row["evidence_id"] for row in visible[0])
            for current in visible[1:]:
                common_ids &= {row["evidence_id"] for row in current}
            all_by_id = {row["evidence_id"]: row for current in visible for row in current}
            common = sorted((all_by_id[eid] for eid in common_ids), key=lambda row: (row["event_time"], row["available_at"], row["evidence_id"]))
            rows.append({
                "semantic_gold_id": f"{chain_id}::{intent_id}",
                "chain_id": chain_id,
                "intent_id": intent_id,
                "query_ids": [query["query_id"] for query in pair],
                "split": "test",
                "query_times": [query["query_time"] for query in pair],
                "visible_evidence_count": len(common),
            })
    return rows


def reconstruct_index_bytes() -> bytes:
    rows = reconstruct_index_rows()
    return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")


def reconstruct_index_sha256() -> str:
    return _sha(reconstruct_index_bytes())


if __name__ == "__main__":
    rows = reconstruct_index_rows()
    print(json.dumps({"rows": len(rows), "private_index_sha256": _sha(reconstruct_index_bytes())}, ensure_ascii=False))
