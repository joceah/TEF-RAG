from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.evaluate_tef_rag_v6_public_generation import evaluate_method, load_gold
from tef_rag_v6.generation_eval import Canonicalizer


ROOT = Path(__file__).parents[1]


def test_released_generation_test_hashes_and_lf_files():
    expected = {
        "gold_test.jsonl": "dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea",
        "gold_test_index.jsonl": "8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35",
    }
    for name, digest in expected.items():
        path = ROOT / "data/generation" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        if name == "gold_test_index.jsonl":
            assert b"\r\n" not in path.read_bytes()


def test_public_generation_wrapper_scores_a_gold_row(tmp_path):
    gold_path = ROOT / "data/generation/gold_development.jsonl"
    query_path = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public/queries_development.jsonl"
    gold = json.loads(gold_path.read_text(encoding="utf-8").splitlines()[0])
    index = json.loads((ROOT / "data/generation/gold_development_index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    query_id = index["query_ids"][0]
    query = next(row for row in (json.loads(line) for line in query_path.read_text(encoding="utf-8").splitlines()) if row["query_id"] == query_id)
    evidence_ids = set(gold["work_order"]["supporting_evidence_ids"])
    for action in gold["action_plan"]:
        evidence_ids.update(action["supporting_evidence_ids"])
    prediction = {"query_id": query_id, "input_evidence_ids": sorted(evidence_ids), "generation": {k: gold[k] for k in ("work_order", "action_plan")}}
    prediction_path = tmp_path / "bm25.jsonl"
    prediction_path.write_text(json.dumps(prediction, ensure_ascii=False) + "\n", encoding="utf-8")
    aliases = json.loads((ROOT / "data/generation/alias_registry.json").read_text(encoding="utf-8"))
    parameters = json.loads((ROOT / "data/generation/parameter_registry.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "data/generation/schema.json").read_text(encoding="utf-8"))
    metrics = evaluate_method(
        prediction_path,
        {query_id: gold},
        {query["query_id"]: query},
        schema,
        Canonicalizer(aliases, parameters),
    )
    assert metrics["task_success"] == 1
