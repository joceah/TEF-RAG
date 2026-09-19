from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tef_rag_v6 import generation_eval_cli as cli
from tef_rag_v6 import generation_runner as runner
from tef_rag_v6.generation_eval import Canonicalizer, evaluate_generation_prediction
from test_tef_rag_v6_generation_eval import canon, gold, schema


def test_unknown_dependency_never_gets_plan_or_dependency_credit():
    g = gold()
    p = copy.deepcopy(g)
    p["action_plan"][1]["depends_on"] = ["UNKNOWN"]
    result = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert result["dependency_f1"] == 0
    assert result["plan_em_strict"] == 0
    assert result["order_validity"] == 0


def test_equivalent_si_units_and_strict_parameter_structure():
    c = Canonicalizer({}, {"aliases": {"voltage": ["电压"]}, "numeric_tolerance": 1e-6})
    assert c.parameters_equal({"电压": {"value": 1000, "unit": "mV"}}, {"voltage": {"value": 1, "unit": "V"}})
    assert not c.parameters_equal({"voltage": {"value": 1.00001, "unit": "V"}}, {"voltage": {"value": 1, "unit": "V"}})
    assert not c.parameters_equal({"voltage": {"value": 1, "unit": "V"}}, {"voltage": {"value": 1, "unit": "A"}})
    assert not c.parameters_equal({"voltage": {"value": 1}}, {"voltage": {"value": 1, "unit": "V"}})


def test_duplicate_canonical_actions_do_not_depend_on_prediction_ids():
    g = gold()
    g["action_plan"].append({**copy.deepcopy(g["action_plan"][0]), "action_id": "A3", "supporting_evidence_ids": ["E2"]})
    p = copy.deepcopy(g)
    p["action_plan"][0]["action_id"] = "X"
    p["action_plan"][2]["action_id"] = "Y"
    p["action_plan"][1]["depends_on"] = ["X"]
    p["work_order"]["recommended_actions"] = ["X"]
    first = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    p["action_plan"][0]["action_id"], p["action_plan"][2]["action_id"] = "Y", "X"
    p["action_plan"][1]["depends_on"] = ["Y"]
    p["work_order"]["recommended_actions"] = ["Y"]
    second = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert first["dependency_f1"] == second["dependency_f1"]
    assert first["citation_f1"] == second["citation_f1"]


def test_extra_duplicate_prediction_selection_is_id_independent():
    g = gold()
    p = copy.deepcopy(g)
    p["action_plan"].append({**copy.deepcopy(p["action_plan"][0]), "action_id": "Z", "supporting_evidence_ids": ["E2"]})
    first = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    p["action_plan"][0]["action_id"] = "ZZ"
    p["action_plan"][1]["depends_on"] = ["ZZ"]
    p["work_order"]["recommended_actions"] = ["ZZ"]
    second = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert first["dependency_f1"] == second["dependency_f1"]
    assert first["citation_f1"] == second["citation_f1"]


def test_official_endpoint_override_rejected_before_cache_access(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "read_env", lambda: {"API_KEY": "test", "ENDPOINT": "https://localhost/chat/completions"})
    with pytest.raises(RuntimeError, match="official DeepSeek endpoint"):
        runner.DeepSeekClient(tmp_path / "cache", official=True)
    assert not (tmp_path / "cache").exists()


def test_preflight_missing_materialized_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "PUBLIC", tmp_path)
    monkeypatch.setattr(cli, "RETRIEVAL_MANIFEST", tmp_path / "retrieval.json")
    monkeypatch.setattr(cli, "GEN_META", tmp_path)
    with pytest.raises(RuntimeError, match="missing required files"):
        cli.preflight()


def test_preflight_rejects_materialized_hash_mismatch(monkeypatch, tmp_path):
    public = tmp_path / "public"
    meta = tmp_path / "metadata"
    public.mkdir()
    meta.mkdir()
    for name in ("queries_test.jsonl", "evidence.jsonl"):
        (public / name).write_text("synthetic\n", encoding="utf-8")
    for name in ("schema.json", "alias_registry.json", "parameter_registry.json", "test_generation_gold_aggregate.json"):
        (meta / name).write_text("{}", encoding="utf-8")
    (meta / "materialized_artifact_hashes.json").write_text(json.dumps({"queries_test.jsonl": "0" * 64}), encoding="utf-8")
    retrieval_manifest = tmp_path / "retrieval.json"
    retrieval_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "PUBLIC", public)
    monkeypatch.setattr(cli, "GEN_META", meta)
    monkeypatch.setattr(cli, "RETRIEVAL_MANIFEST", retrieval_manifest)
    monkeypatch.setattr(cli, "queries", lambda: [{"query_id": "Q1"}])
    with pytest.raises(RuntimeError, match="materialized artifact hash missing or changed"):
        cli.preflight()


def test_private_gold_requires_frozen_mapping_before_read(monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("sentinel", encoding="utf-8")
    (private / "gold_test_index.jsonl").write_text("sentinel", encoding="utf-8")
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "test_generation_gold_aggregate.json").write_text(json.dumps({"private_gold_sha256": "0" * 64}), encoding="utf-8")
    monkeypatch.setattr(cli, "GEN_META", metadata)
    with pytest.raises(RuntimeError, match="lacks private_index_sha256"):
        cli.load_private_gold(private)


def test_private_index_hash_mismatch_rejected(monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("synthetic\n", encoding="utf-8")
    (private / "gold_test_index.jsonl").write_text("synthetic\n", encoding="utf-8")
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "test_generation_gold_aggregate.json").write_text(json.dumps({
        "private_gold_sha256": cli.sha256(private / "gold_test.jsonl"),
        "private_index_sha256": "0" * 64,
        "semantic_gold_sha256_by_id": {str(i): str(i) for i in range(240)},
    }), encoding="utf-8")
    monkeypatch.setattr(cli, "GEN_META", metadata)
    with pytest.raises(RuntimeError, match="index SHA mismatch"):
        cli.load_private_gold(private)


def test_repeated_formal_evaluation_rejected_before_private_access(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "OUT", tmp_path)
    (tmp_path / "final_evaluation_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already completed"):
        cli.evaluate(tmp_path / "private")


def test_evaluation_rejects_evaluator_mutation_before_private_access(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "OUT", tmp_path)
    (tmp_path / "generation_prediction_manifest.json").write_text(json.dumps({"scoring_fingerprint": {"evaluator_sha256": "old"}}), encoding="utf-8")
    monkeypatch.setattr(cli, "scoring_fingerprint", lambda: {"evaluator_sha256": "changed"})
    with pytest.raises(RuntimeError, match="frozen evaluator"):
        cli.evaluate(tmp_path / "private")


def test_scoring_fingerprint_changes_with_evaluator_or_registry(monkeypatch, tmp_path):
    root = tmp_path
    meta = root / "meta"
    meta.mkdir()
    for name in ("schema.json", "alias_registry.json", "parameter_registry.json"):
        (meta / name).write_text("{}", encoding="utf-8")
    for name in cli.EVALUATOR_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("version one", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "GEN_META", meta)
    original = cli.scoring_fingerprint()
    (meta / "alias_registry.json").write_text("changed", encoding="utf-8")
    assert cli.scoring_fingerprint() != original
    (meta / "alias_registry.json").write_text("{}", encoding="utf-8")
    (root / cli.EVALUATOR_FILES[0]).write_text("version two", encoding="utf-8")
    assert cli.scoring_fingerprint() != original
