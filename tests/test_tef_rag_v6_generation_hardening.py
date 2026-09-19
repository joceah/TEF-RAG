from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tef_rag_v6 import generation_eval_cli as cli
from tef_rag_v6 import generation_runner as runner
from tef_rag_v6.generation_eval import Canonicalizer, evaluate_generation_prediction, validate_generation_output, validate_gold_action_uniqueness
from scripts.reconstruct_tef_v6_generation_private_index import reconstruct_index_sha256, reconstruct_index_rows
from test_tef_rag_v6_generation_eval import canon, gold, schema


def test_frozen_retrieval_length_distributions_are_preserved():
    expected = {
        "bm25": {5: 470, 3: 10},
        "bge_reranker": {5: 470, 3: 10},
        "temporal_bm25": {5: 470, 3: 10},
        "ta_rag": {5: 435, 3: 10, 0: 35},
        "tef_rag_stage3d": {5: 470, 3: 10},
    }
    actual = {}
    manifest = runner.read_json(runner.RETRIEVAL_MANIFEST)
    for method, rows in runner.retrieval_predictions().items():
        assert runner.sha256(runner.retrieval_paths()[method]) == manifest["predictions"][method]["prediction_sha256"]
        counts = {}
        for row in rows:
            size = len(row["selected_evidence_ids"])
            counts[size] = counts.get(size, 0) + 1
        actual[method] = counts
    assert actual == expected


def test_short_output_protocol_version_is_sealed():
    assert runner.GENERATION_PROTOCOL_VERSION == "v1.7-transport-syntax-normalization"
    assert cli.scoring_fingerprint()["protocol_version"] == runner.GENERATION_PROTOCOL_VERSION


def test_canonical_model_is_bound_in_request_payload_and_session():
    assert runner.MODEL == "deepseek-flash"
    query = {"query_id": "Q", "query_text": "test", "query_time": "2021-01-01T00:00:00+00:00", "asset_id": "Rack-A"}
    system, user = runner.build_prompt(query, [], schema())
    payload = runner.request_payload(system, user)
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    pre = {
        "retrieval_prediction_hashes": {method: f"{method}-hash" for method in cli.METHODS},
        "materialized_artifact_hashes": {"queries_test.jsonl": "q", "evidence.jsonl": "e"},
    }
    baseline = cli.formal_session_fingerprint(pre)
    original_model = cli.MODEL
    original_protocol = cli.GENERATION_PROTOCOL_VERSION
    try:
        cli.MODEL = "deepseek-v4-flash"
        assert cli.formal_session_fingerprint(pre) != baseline
        cli.MODEL = original_model
        cli.GENERATION_PROTOCOL_VERSION = "v1.5-model-correction"
        assert cli.formal_session_fingerprint(pre) != baseline
    finally:
        cli.MODEL = original_model
        cli.GENERATION_PROTOCOL_VERSION = original_protocol


def test_model_correction_preserves_prompt_schema_retrieval_and_repair_contract():
    assert runner.PROMPT_VERSION == "tef-v6-generation-eval-v1.3"
    assert runner.TEMPERATURE == 0.0
    query = {"query_id": "Q", "query_text": "test", "query_time": "2021-01-01T00:00:00+00:00", "asset_id": "Rack-A"}
    system, user = runner.build_prompt(query, [], schema())
    payload = runner.request_payload(system, user)
    assert payload["temperature"] == 0.0
    assert payload["response_format"] == {"type": "json_object"}
    assert runner.sha_text(runner.generator_instructions()) == "07ce267fc5a7b4da0675723acd3f6d79dbe7ea83f882193da7133fc88fc61e74"
    assert runner.sha256(runner.GEN_META / "schema.json") == "dfdbd8a38c9be95138a55af8f7672c33a3b25e3d3f8189d0e0edb7957334ab85"
    manifest = runner.read_json(runner.RETRIEVAL_MANIFEST)
    assert cli.expected_retrieval_hashes() == {
        method: manifest["predictions"][method]["prediction_sha256"]
        for method in cli.METHODS
    }
    assert "one repair" in Path("markdowns/tef_rag_v6_generation_evaluation_v1.md").read_text(encoding="utf-8").lower()


def test_old_session_partial_rows_fail_closed_before_resume():
    with pytest.raises(RuntimeError, match="different formal session"):
        cli.ensure_clean_generation_restart(
            {"bm25": [{"session_fingerprint": "a8db-deepseek-chat"}]},
            "v1.5-deepseek-flash",
        )


def test_thinking_configuration_changes_request_and_session_fingerprints(monkeypatch):
    query = {"query_id": "Q", "query_text": "test", "query_time": "2021-01-01T00:00:00+00:00", "asset_id": "Rack-A"}
    system, user = runner.build_prompt(query, [], schema())
    baseline_request = runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user)
    pre = {
        "retrieval_prediction_hashes": {method: f"{method}-hash" for method in cli.METHODS},
        "materialized_artifact_hashes": {"queries_test.jsonl": "q", "evidence.jsonl": "e"},
    }
    baseline_session = cli.formal_session_fingerprint(pre)
    monkeypatch.setattr(runner, "THINKING_MODE", "enabled")
    monkeypatch.setattr(cli, "THINKING_MODE", "enabled")
    assert runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user) != baseline_request
    assert cli.formal_session_fingerprint(pre) != baseline_session


def test_transport_protocol_changes_session_but_not_request_fingerprint(monkeypatch):
    pre = {
        "retrieval_prediction_hashes": {method: f"{method}-hash" for method in cli.METHODS},
        "materialized_artifact_hashes": {"queries_test.jsonl": "q", "evidence.jsonl": "e"},
    }
    current_session = cli.formal_session_fingerprint(pre)
    monkeypatch.setattr(cli, "GENERATION_PROTOCOL_VERSION", "v1.6-nonthinking-runtime-clarification")
    assert cli.formal_session_fingerprint(pre) != current_session
    query = next(row for row in runner.queries() if row["query_id"] == "TEFV6-C0017-I01-current_cause_action-P2")
    retrieval_row = next(row for row in runner.retrieval_predictions()["bm25"] if row["query_id"] == query["query_id"])
    evidence = runner.evidence_map()
    system, user = runner.build_prompt(query, [evidence[eid] for eid in retrieval_row["selected_evidence_ids"]], runner.schema())
    assert runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user) == "540da1cc4c43bd83bf1e158636797a77610db90cdcd5a6b92dc0443bcfa425c1"


@pytest.mark.parametrize(
    "raw,mode,expected",
    [
        ('{"a":1}', "strict", {"a": 1}),
        ('{"a":1}}', "single_extra_closing_brace", {"a": 1}),
    ],
)
def test_generation_parser_accepts_only_strict_object_or_one_extra_brace(raw, mode, expected):
    result, provenance = runner.parse_generation_json_object(raw)
    assert result == expected
    assert provenance["parse_mode"] == mode
    assert runner.validate_parse_provenance(provenance) == []
    if mode == "strict":
        assert provenance["normalization_removed_chars"] == 0
        assert provenance["accepted_json_text_sha256"] == provenance["cleaned_content_sha256"]
    else:
        assert provenance["normalization_removed_chars"] == 1
        assert provenance["accepted_json_text_length"] == provenance["cleaned_content_length"] - 1


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":1}}}',
        '{"a":1} garbage',
        '{"a":1} }',
        '{"a":',
        '{"a":"unterminated}',
        '[1,2]}',
    ],
)
def test_generation_parser_rejects_other_malformed_or_trailing_content(raw):
    with pytest.raises((json.JSONDecodeError, ValueError)):
        runner.parse_generation_json_object(raw)


def test_strict_parser_does_not_change_valid_json():
    raw = '  \ufeff{"a":1}  '
    result, provenance = runner.parse_generation_json_object(raw)
    assert result == {"a": 1}
    assert provenance["parse_mode"] == "strict"
    assert provenance["normalization_removed_chars"] == 0


def test_cache_hit_restores_parse_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "read_env", lambda: {"API_KEY": "test"})
    system, user = "system", "user"
    _, provenance = runner.parse_generation_json_object('{"ok":true}}')
    request_hash = runner.request_fingerprint(runner.BASE_URL.rstrip("/") + "/chat/completions", system, user)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{request_hash}.json").write_text(json.dumps({"result": {"ok": True}, "usage": {}, "parse_provenance": provenance}), encoding="utf-8")
    monkeypatch.setattr(runner.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("cache hit made a network request"))
    client = runner.DeepSeekClient(cache, official=True)
    assert client.call(system, user, "cache") == {"ok": True}
    assert client.last_parse_provenance == provenance


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def _client_for_response(monkeypatch, tmp_path, envelope):
    monkeypatch.setattr(runner, "read_env", lambda: {"API_KEY": "test"})
    monkeypatch.setattr(runner, "CALL_INTERVAL", 0.0)
    calls = []
    body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeResponse(body)

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    return runner.DeepSeekClient(tmp_path / "cache", official=True), calls


def test_finish_reason_length_is_transport_failure_before_json_parse(monkeypatch, tmp_path):
    client, calls = _client_for_response(
        monkeypatch,
        tmp_path,
        {"choices": [{"finish_reason": "length", "message": {"content": '{"partial":1}}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "completion_tokens_details": {"reasoning_tokens": 19}}},
    )
    with pytest.raises(RuntimeError, match="ValueError"):
        client.call("system", "user", "length")
    assert len(calls) == 3
    assert client.stats["failures"] == 1
    assert client.stats["retries"] == 2
    assert client.stats["prompt_tokens"] == 30
    assert client.stats["completion_tokens"] == 60
    assert client.stats["total_tokens"] == 90
    assert client.stats["reasoning_tokens"] == 57
    assert not list((tmp_path / "cache").glob("*.json"))


def test_finish_reason_stop_valid_json_is_returned(monkeypatch, tmp_path):
    client, calls = _client_for_response(
        monkeypatch,
        tmp_path,
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "completion_tokens_details": {"reasoning_tokens": 0}}},
    )
    assert client.call("system", "user", "stop") == {"ok": True}
    assert len(calls) == 1
    assert client.stats["reasoning_tokens"] == 0


def test_finish_reason_stop_extra_brace_uses_transport_normalization(monkeypatch, tmp_path):
    client, calls = _client_for_response(
        monkeypatch,
        tmp_path,
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
    )
    assert client.call("system", "user", "normalized") == {"ok": True}
    assert len(calls) == 1
    assert client.last_parse_provenance["parse_mode"] == "single_extra_closing_brace"
    cached = next((tmp_path / "cache").glob("*.json"))
    assert json.loads(cached.read_text(encoding="utf-8"))["parse_provenance"]["parse_mode"] == "single_extra_closing_brace"


def test_finish_reason_stop_malformed_json_keeps_parser_retry_behavior(monkeypatch, tmp_path):
    client, calls = _client_for_response(
        monkeypatch,
        tmp_path,
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"bad":'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
    )
    with pytest.raises(RuntimeError, match="JSONDecodeError"):
        client.call("system", "user", "malformed")
    assert len(calls) == 3


def _visible_evidence(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "event_time": "2020-01-01T00:00:00+00:00",
        "available_at": "2020-01-01T00:00:00+00:00",
    }


def _cardinality_query() -> dict[str, str]:
    return {"query_id": "Q", "query_time": "2021-01-01T00:00:00+00:00", "asset_model": "M"}


def test_short_retrieval_outputs_pass_without_padding_or_backfill():
    query = _cardinality_query()
    evidence = {f"E{i}": _visible_evidence(f"E{i}") for i in range(6)}
    for size in (0, 3, 5):
        row = {"selected_evidence_ids": [f"E{i}" for i in range(size)]}
        original = list(row["selected_evidence_ids"])
        assert cli.validate_selected_evidence_ids(query, row, evidence) == []
        assert row["selected_evidence_ids"] == original
    assert cli.validate_selected_evidence_ids(query, {"selected_evidence_ids": [f"E{i}" for i in range(6)]}, evidence)
    assert cli.validate_selected_evidence_ids(query, {"selected_evidence_ids": ["E1", "E1"]}, evidence)
    assert cli.validate_selected_evidence_ids(query, {"selected_evidence_ids": ["UNKNOWN"]}, evidence)
    invisible = _visible_evidence("E-invisible")
    invisible["available_at"] = "2022-01-01T00:00:00+00:00"
    assert cli.validate_selected_evidence_ids(query, {"selected_evidence_ids": ["E-invisible"]}, {"E-invisible": invisible})


def test_empty_selected_evidence_prompt_and_scoring_path_is_safe():
    query = {"query_id": "Q", "query_text": "test", "query_time": "2021-01-01T00:00:00+00:00", "asset_id": "Rack-A"}
    _, user = runner.build_prompt(query, [], schema())
    assert json.loads(user)["selected_evidence"] == []
    prediction = gold()
    prediction["work_order"]["supporting_evidence_ids"] = []
    for field in ("diagnosis", "applicable_procedure", "verification_or_uncertainty"):
        prediction["work_order"][field]["supporting_evidence_ids"] = []
    for action in prediction["action_plan"]:
        action["supporting_evidence_ids"] = []
    assert validate_generation_output(prediction, schema(), set(), "Rack-A") == []
    result = evaluate_generation_prediction(prediction, gold(), schema(), canon(), set(), "Rack-A")
    assert result["schema_validity"] == 1
    assert result["evidence_support_recall"] == 0


def test_unknown_dependency_never_gets_plan_or_dependency_credit():
    g = gold()
    p = copy.deepcopy(g)
    p["action_plan"][1]["depends_on"] = ["UNKNOWN"]
    result = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert result["dependency_f1"] == 0
    assert result["plan_em_strict"] == 0
    assert result["order_validity"] == 0


def test_unknown_dependency_when_gold_has_no_edges_is_false_positive():
    g = gold()
    g["action_plan"][1]["depends_on"] = []
    p = copy.deepcopy(g)
    p["action_plan"][1]["depends_on"] = ["UNKNOWN"]
    result = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert result["dependency_f1"] < 1
    assert result["order_validity"] == result["plan_em_strict"] == result["schema_validity"] == 0


def test_public_only_reconstruction_matches_frozen_private_index_hash():
    aggregate = runner.read_json(runner.GEN_META / "test_generation_gold_aggregate.json")
    assert len(reconstruct_index_rows()) == 240
    assert reconstruct_index_sha256() == aggregate["private_index_sha256"]
    assert "semantic_gold_sha256_by_id" not in aggregate


def test_equivalent_si_units_and_strict_parameter_structure():
    c = Canonicalizer({}, {"aliases": {"voltage": ["电压"]}, "numeric_tolerance": 1e-6})
    assert c.parameters_equal({"电压": {"value": 1000, "unit": "mV"}}, {"voltage": {"value": 1, "unit": "V"}})
    assert not c.parameters_equal({"voltage": {"value": 1.00001, "unit": "V"}}, {"voltage": {"value": 1, "unit": "V"}})
    assert not c.parameters_equal({"voltage": {"value": 1, "unit": "V"}}, {"voltage": {"value": 1, "unit": "A"}})
    assert not c.parameters_equal({"voltage": {"value": 1}}, {"voltage": {"value": 1, "unit": "V"}})
    assert c.parameters_equal(
        {"voltage": {"value": {"lower": 1000, "upper": 2000}, "unit": "mV"}},
        {"voltage": {"value": {"lower": 1, "upper": 2}, "unit": "V"}},
    )
    assert not c.parameters_equal(
        {"voltage": {"value": {"lower": 1000, "upper": 2000}, "unit": "mV"}},
        {"voltage": {"value": 1.5, "unit": "V"}},
    )


def test_published_gold_parameter_compatibility_and_malformed_rejection():
    from scripts.generate_tef_v6_generation_gold_v1 import schema_document
    root = runner.GEN_META.parent
    actual_schema = runner.schema()
    assert schema_document() == actual_schema
    validator = Draft202012Validator(actual_schema)
    for split in ("development", "validation"):
        rows = runner.read_jsonl(root / "public" / f"gold_{split}.jsonl")
        assert all(not list(validator.iter_errors(row)) for row in rows)
        public_canon = Canonicalizer(runner.aliases(), runner.parameters())
        for row in rows:
            validate_gold_action_uniqueness(row, public_canon)
    bad = gold()
    bad["action_plan"][0]["parameters"] = {"voltage": {"foo": "bar"}}
    assert validate_generation_output(bad, actual_schema, {"E1", "E2"}, "Rack-A")
    bad["action_plan"][0]["parameters"] = {"voltage": {"value": {"lower": 2, "upper": 1}, "unit": "V"}}
    assert "parameter range lower exceeds upper" in validate_generation_output(bad, actual_schema, {"E1", "E2"}, "Rack-A")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda prediction: prediction["action_plan"][1].__setitem__("depends_on", None),
        lambda prediction: prediction["action_plan"][0].__setitem__("supporting_evidence_ids", None),
        lambda prediction: prediction["work_order"].__setitem__("recommended_actions", None),
        lambda prediction: prediction["action_plan"][0].__setitem__("action_type", {}),
        lambda prediction: prediction["action_plan"][0].__setitem__("parameters", None),
        lambda prediction: prediction["action_plan"].append("not an action object"),
        lambda prediction: prediction.__setitem__("work_order", []),
        lambda prediction: prediction["work_order"].__setitem__("diagnosis", []),
    ],
    ids=[
        "depends_on-none",
        "supporting-evidence-none",
        "recommended-actions-none",
        "action-type-object",
        "parameters-none",
        "action-plan-non-object",
        "work-order-wrong-type",
        "diagnosis-wrong-type",
    ],
)
def test_malformed_json_object_prediction_is_safe_and_conservative(mutate):
    prediction = gold()
    mutate(prediction)
    errors = validate_generation_output(prediction, schema(), {"E1", "E2"}, "Rack-A")
    assert errors
    result = evaluate_generation_prediction(prediction, gold(), schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert result["schema_validity"] == 0
    assert result["plan_em_strict"] == 0
    assert result["task_success"] == 0


def test_duplicate_canonical_gold_fails_closed():
    g = gold()
    g["action_plan"].append({**copy.deepcopy(g["action_plan"][0]), "action_id": "A3", "supporting_evidence_ids": ["E2"]})
    with pytest.raises(RuntimeError, match="duplicate canonical actions"):
        evaluate_generation_prediction(g, g, schema(), canon(), {"E1", "E2"}, "Rack-A")


def test_extra_duplicate_prediction_selection_is_id_independent():
    g = gold()
    p = copy.deepcopy(g)
    p["action_plan"].append({**copy.deepcopy(p["action_plan"][0]), "action_id": "Z", "supporting_evidence_ids": ["E2"]})
    first = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    p["action_plan"][0]["action_id"] = "ZZ"
    p["action_plan"][1]["depends_on"] = ["ZZ"]
    p["work_order"]["recommended_actions"] = ["ZZ"]
    second = evaluate_generation_prediction(p, g, schema(), canon(), {"E1", "E2"}, "Rack-A")
    assert first == second


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
    (tmp_path / "manifest.json").write_text(json.dumps({"public_artifact_hashes": {"public/queries_test.jsonl": "1" * 64}}), encoding="utf-8")
    (tmp_path / "transport_manifest.json").write_text(json.dumps({"public/queries_test.jsonl": {"uncompressed_sha256": "1" * 64}}), encoding="utf-8")
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
    monkeypatch.setattr(cli, "sha256", lambda path: pytest.fail("private file content read before index metadata gate"))
    with pytest.raises(RuntimeError, match="lacks private_index_sha256"):
        cli.load_private_gold(private)


def test_frozen_manifest_locks_both_private_aggregate_hashes():
    pre = {
        "private_generation_gold_expected_sha256": "g" * 64,
        "private_generation_index_expected_sha256": "i" * 64,
    }
    manifest = dict(pre)
    cli.validate_frozen_private_seal(manifest, pre)
    manifest["private_generation_index_expected_sha256"] = "x" * 64
    with pytest.raises(RuntimeError, match="private index expected SHA changed"):
        cli.validate_frozen_private_seal(manifest, pre)


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
    }), encoding="utf-8")
    monkeypatch.setattr(cli, "GEN_META", metadata)
    with pytest.raises(RuntimeError, match="index SHA mismatch"):
        cli.load_private_gold(private)


def test_two_aggregate_hashes_authorize_synthetic_row_pairing(monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    gold_path = private / "gold_test.jsonl"
    index_path = private / "gold_test_index.jsonl"
    gold_path.write_text("".join(json.dumps({"ordinal": i}) + "\n" for i in range(240)), encoding="utf-8")
    index_path.write_text("".join(json.dumps({"semantic_gold_id": f"S{i}", "query_ids": [f"Q{i}a", f"Q{i}b"]}) + "\n" for i in range(240)), encoding="utf-8")
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    document = {"private_gold_sha256": cli.sha256(gold_path), "private_index_sha256": cli.sha256(index_path)}
    (metadata / "test_generation_gold_aggregate.json").write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(cli, "GEN_META", metadata)
    paired, _, _ = cli.load_private_gold(private)
    assert paired["Q17b"] == {"ordinal": 17}
    assert len(paired) == 480
    assert set(document) == {"private_gold_sha256", "private_index_sha256"}


def test_private_output_inside_repo_rejected_before_access(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="outside repository root"):
        cli.evaluate(tmp_path / "private")


def test_private_gold_schema_gate_rejects_before_scoring():
    bad = gold()
    bad["action_plan"][0]["parameters"] = {"voltage": {"foo": "bar"}}
    with pytest.raises(RuntimeError, match="failed v1.3 schema"):
        cli.validate_private_gold_objects({"Q1": bad}, runner.schema(), canon())


def test_post_repair_invalid_prediction_is_retained_for_freeze_validation():
    query = {"query_id": "Q1", "asset_id": "Rack-A", "query_text": "test", "query_time": "2026-01-01T00:00:00+00:00"}
    selected = ["E1"]
    records = [{"evidence_id": "E1", "text": "test"}]
    output_schema = runner.schema()
    system, user = runner.build_prompt(query, records, output_schema)
    initial = {"not": "valid schema"}
    initial_errors = validate_generation_output(initial, output_schema, set(selected), query["asset_id"])
    repair_system, repair_user = runner.repair_prompt(query, records, initial, initial_errors, output_schema)
    final = {"still": "invalid"}
    final_errors = validate_generation_output(final, output_schema, set(selected), query["asset_id"])
    _, initial_parse_provenance = runner.parse_generation_json_object(json.dumps(initial))
    _, repair_parse_provenance = runner.parse_generation_json_object(json.dumps(final))
    row = {
        "generation": final,
        "repair_used": True,
        "initial_generation": initial,
        "initial_validation_errors": initial_errors,
        "validation_errors": final_errors,
        "initial_parse_provenance": initial_parse_provenance,
        "repair_parse_provenance": repair_parse_provenance,
        "session_fingerprint": "session",
        "initial_request_fingerprint": runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user),
        "repair_request_fingerprint": runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, repair_system, repair_user),
        "request_provenance": {"endpoint": cli.OFFICIAL_ENDPOINT, "model": runner.MODEL, "prompt_sha256": runner.sha_text(runner.generator_instructions()), "schema_sha256": runner.sha256(runner.GEN_META / "schema.json"), "temperature": runner.TEMPERATURE, "max_tokens": runner.MAX_TOKENS, "thinking_mode": "disabled"},
    }
    assert cli.validate_generation_row(row, query, selected, records, output_schema, "session") == final_errors
    assert final_errors


def test_repeated_formal_evaluation_rejected_before_private_access(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "OUT", tmp_path)
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("synthetic", encoding="utf-8")
    (private / "gold_test_index.jsonl").write_text("synthetic", encoding="utf-8")
    (tmp_path / "final_evaluation_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already completed"):
        cli.evaluate(private)


def test_existing_evaluation_start_lock_rejected_before_private_access(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    out = root / "out"
    out.mkdir(parents=True)
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "OUT", out)
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("synthetic", encoding="utf-8")
    (private / "gold_test_index.jsonl").write_text("synthetic", encoding="utf-8")
    (out / "evaluation_started.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="already completed"):
        cli.evaluate(private)


def test_evaluation_start_lock_is_atomic_one_shot(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    start = tmp_path / "evaluation_started.json"
    cli.claim_formal_evaluation_once(start, manifest)
    assert cli.read_json(start)["generation_prediction_manifest_sha256"] == cli.sha256(manifest)
    with pytest.raises(RuntimeError, match="already started"):
        cli.claim_formal_evaluation_once(start, manifest)


def test_evaluation_rejects_evaluator_mutation_before_private_access(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "OUT", tmp_path)
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("synthetic", encoding="utf-8")
    (private / "gold_test_index.jsonl").write_text("synthetic", encoding="utf-8")
    (tmp_path / "generation_prediction_manifest.json").write_text(json.dumps({"scoring_fingerprint": {"evaluator_sha256": "old"}}), encoding="utf-8")
    monkeypatch.setattr(cli, "scoring_fingerprint", lambda: {"evaluator_sha256": "changed"})
    with pytest.raises(RuntimeError, match="frozen evaluator"):
        cli.evaluate(private)


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
    (root / cli.EVALUATOR_FILES[0]).write_text("version one", encoding="utf-8")
    (root / "tef_rag_v6/generation_runner.py").write_text("runner changed", encoding="utf-8")
    assert cli.scoring_fingerprint() != original


def test_request_fingerprints_reconstruct_initial_and_repair_payload():
    query = {"query_id": "Q", "query_text": "test", "query_time": "2026-01-01T00:00:00+00:00", "asset_id": "Rack-A"}
    selected = [{"evidence_id": "E1", "text": "test"}]
    system, user = runner.build_prompt(query, selected, schema())
    first = runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user)
    assert first == runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, system, user)
    repair_system, repair_user = runner.repair_prompt(query, selected, {"bad": True}, ["schema:error"], schema())
    repair = runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, repair_system, repair_user)
    assert repair != first
    assert repair == runner.request_fingerprint(cli.OFFICIAL_ENDPOINT, repair_system, repair_user)


def test_resume_session_mismatch_rejected_before_client(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "OUT", tmp_path)
    monkeypatch.setattr(cli, "preflight", lambda: {})
    monkeypatch.setattr(cli, "formal_session_fingerprint", lambda pre: "current")
    monkeypatch.setattr(cli, "queries", lambda: [{"query_id": "Q", "asset_id": "Rack-A"}])
    monkeypatch.setattr(cli, "evidence_map", lambda: {"E1": {"evidence_id": "E1"}})
    monkeypatch.setattr(cli, "retrieval_predictions", lambda: {method: [{"selected_evidence_ids": ["E1"]}] for method in cli.METHODS})
    monkeypatch.setattr(cli, "schema", lambda: schema())
    monkeypatch.setattr(cli, "load_generation_rows", lambda method: [{"query_id": "Q", "input_evidence_ids": ["E1"], "session_fingerprint": "old"}] if method == cli.METHODS[0] else [])
    monkeypatch.setattr(cli, "DeepSeekClient", lambda *args, **kwargs: pytest.fail("client accessed before resume validation"))
    with pytest.raises(RuntimeError, match="resume session mismatch"):
        cli.run_generation(cli.METHODS)


def test_formal_cli_rejects_method_mode():
    from scripts.run_tef_rag_v6_generation_eval import main
    with pytest.raises(SystemExit):
        main(["generate", "--method", "bm25"])
    with pytest.raises(SystemExit, match="requires --all"):
        main(["generate"])


def test_public_materialized_hashes_match_frozen_transport_provenance():
    materialized = runner.read_json(runner.GEN_META / "materialized_artifact_hashes.json")
    benchmark = runner.read_json(runner.PUBLIC.parent / "manifest.json")
    transport = runner.read_json(runner.PUBLIC.parent / "transport_manifest.json")
    for name in ("queries_test.jsonl", "evidence.jsonl"):
        assert materialized[name] == benchmark["public_artifact_hashes"][f"public/{name}"]
        assert materialized[name] == transport[f"public/{name}"]["uncompressed_sha256"]
