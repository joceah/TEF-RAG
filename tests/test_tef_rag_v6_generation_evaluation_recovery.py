from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_tef_rag_v6_generation_eval_index_newline_recovery as recovery


def _rows(count=240):
    return [{"semantic_gold_id": f"C{i}::I0", "query_ids": [f"Q{i}a", f"Q{i}b"], "value": i} for i in range(count)]


def _bytes(rows):
    return "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows).encode()


def _expected(raw):
    return hashlib.sha256(raw).hexdigest()


def _setup_public_prechecks(monkeypatch, tmp_path, *, include_original_lock=True):
    root = tmp_path / "repo"
    out = root / "results"
    root.mkdir()
    out.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    canonical = _bytes(_rows())
    actual = canonical.replace(b"\n", b"\r\n")
    (private / "gold_test.jsonl").write_text("{}\n" * 240, encoding="utf-8")
    (private / "gold_test_index.jsonl").write_bytes(actual)
    scoring = {"evaluator_sha256": {"synthetic": "sha"}}
    pre = {
        "retrieval_prediction_hashes": {"synthetic": "prediction"},
        "materialized_artifact_hashes": {"queries_test.jsonl": "q", "evidence.jsonl": "e"},
        "private_generation_gold_expected_sha256": _expected((private / "gold_test.jsonl").read_bytes()),
        "private_generation_index_expected_sha256": _expected(canonical),
    }
    manifest = {
        "private_generation_gold_accessed": False,
        "private_generation_gold_expected_sha256": pre["private_generation_gold_expected_sha256"],
        "private_generation_index_expected_sha256": pre["private_generation_index_expected_sha256"],
        "scoring_fingerprint": scoring,
        "retrieval_prediction_hashes": pre["retrieval_prediction_hashes"],
        "materialized_artifact_hashes": pre["materialized_artifact_hashes"],
        "generation_prediction_hashes": {"synthetic": "prediction"},
    }
    manifest_path = out / "generation_prediction_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = _expected(manifest_path.read_bytes())
    if include_original_lock:
        (out / "evaluation_started.json").write_text(json.dumps({"status": "FORMAL_EVALUATION_STARTED", "generation_prediction_manifest_sha256": manifest_sha}), encoding="utf-8")
    monkeypatch.setattr(recovery.cli, "ROOT", root)
    monkeypatch.setattr(recovery.cli, "OUT", out)
    monkeypatch.setattr(recovery, "EXPECTED_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(recovery.cli, "scoring_fingerprint", lambda: scoring)
    monkeypatch.setattr(recovery.cli, "preflight", lambda: pre)
    monkeypatch.setattr(recovery.cli, "validate_frozen_private_seal", lambda *_: None)
    monkeypatch.setattr(recovery.cli, "formal_session_fingerprint", lambda _: "session")
    monkeypatch.setattr(recovery.cli, "validate_generation_files", lambda _: {"synthetic": "prediction"})
    monkeypatch.setattr(recovery, "reconstruct_index_bytes", lambda: canonical)
    monkeypatch.setattr(recovery, "reconstruct_index_rows", lambda: _rows())
    return root, out, private, manifest, canonical, actual


def test_exact_crlf_transport_accepts_only_exact_variant():
    canonical = _bytes(_rows())
    actual = canonical.replace(b"\n", b"\r\n")
    result = recovery.validate_exact_crlf_transport(actual, canonical, expected_raw_sha256=_expected(actual), expected_rows=240)
    assert result["transport_equivalence"] == "exact_lf_to_crlf"


@pytest.mark.parametrize("mutate", [
    lambda b: b[:-1],
    lambda b: b + b"\r\n",
    lambda b: b"\xef\xbb\xbf" + b,
    lambda b: b.replace(b"\r\n", b"\rX\n", 1),
    lambda b: b.replace(b"\r\n", b"\n", 1),
    lambda b: b.replace(b"\r\n", b"\r", 1),
])
def test_crlf_transport_rejects_shape_changes(mutate):
    canonical = _bytes(_rows())
    actual = mutate(canonical.replace(b"\n", b"\r\n"))
    with pytest.raises(RuntimeError):
        recovery.validate_exact_crlf_transport(actual, canonical, expected_raw_sha256=_expected(actual), expected_rows=240)


def test_wrong_raw_sha_rejected():
    canonical = _bytes(_rows())
    with pytest.raises(RuntimeError, match="raw SHA"):
        recovery.validate_exact_crlf_transport(canonical.replace(b"\n", b"\r\n"), canonical, expected_raw_sha256="0" * 64, expected_rows=240)


def test_index_semantics_require_order_fields_ids_and_coverage():
    rows = _rows()
    assert recovery.validate_index_semantics(rows, copy.deepcopy(rows), expected_rows=240, expected_query_coverage=480)["query_coverage"] == 480
    for mutate in (
        lambda x: x.reverse(),
        lambda x: x[0].__setitem__("value", 99),
        lambda x: x[0].__setitem__("semantic_gold_id", x[1]["semantic_gold_id"]),
        lambda x: x[0].__setitem__("query_ids", ["Q0a"]),
    ):
        bad = copy.deepcopy(rows)
        mutate(bad)
        with pytest.raises(RuntimeError):
            recovery.validate_index_semantics(bad, rows, expected_rows=240, expected_query_coverage=480)


def test_pairing_requires_unique_480_query_ids():
    rows = _rows()
    gold = [{"ordinal": i} for i in range(240)]
    paired = recovery._pair_private_rows(gold, rows)
    assert len(paired) == 480
    duplicate = copy.deepcopy(rows)
    duplicate[1]["query_ids"][0] = duplicate[0]["query_ids"][0]
    with pytest.raises(RuntimeError):
        recovery._pair_private_rows(gold, duplicate)


def test_atomic_recovery_lock_is_one_shot(tmp_path):
    lock = tmp_path / recovery.RECOVERY_LOCK_NAME
    recovery._atomic_recovery_lock(lock, manifest_sha256="m" * 64, original_lock_sha256="o" * 64)
    assert json.loads(lock.read_text())["status"] == "FORMAL_EVALUATION_RECOVERY_STARTED"
    with pytest.raises(RuntimeError, match="already started"):
        recovery._atomic_recovery_lock(lock, manifest_sha256="m" * 64, original_lock_sha256="o" * 64)


def test_public_prechecks_fail_closed_before_private_access(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery, "EXPECTED_MANIFEST_SHA256", "0" * 64)
    private = tmp_path / "private"
    private.mkdir()
    (private / "gold_test.jsonl").write_text("sentinel")
    (private / "gold_test_index.jsonl").write_text("sentinel")
    with pytest.raises(RuntimeError, match="manifest SHA"):
        recovery.public_prechecks(private)
    assert not (private / recovery.RECOVERY_DETAILS_NAME).exists()


def test_public_prechecks_reject_missing_original_lock(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path, include_original_lock=False)
    with pytest.raises(RuntimeError, match="original evaluation lock"):
        recovery.public_prechecks(private)


def test_public_prechecks_reject_original_lock_manifest_mismatch(monkeypatch, tmp_path):
    _, out, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    lock = out / "evaluation_started.json"
    lock.write_text(json.dumps({"status": "FORMAL_EVALUATION_STARTED", "generation_prediction_manifest_sha256": "x" * 64}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="original evaluation lock"):
        recovery.public_prechecks(private)


@pytest.mark.parametrize("name", ["metrics.json", "final_evaluation_manifest.json"])
def test_public_prechecks_reject_original_output(monkeypatch, tmp_path, name):
    _, out, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    (out / name).write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="original evaluation output"):
        recovery.public_prechecks(private)


def test_public_prechecks_reject_scoring_fingerprint_change(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery.cli, "scoring_fingerprint", lambda: {"changed": True})
    with pytest.raises(RuntimeError, match="frozen evaluator"):
        recovery.public_prechecks(private)


def test_public_prechecks_reject_prediction_hash_change(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery.cli, "validate_generation_files", lambda _: {"synthetic": "changed"})
    with pytest.raises(RuntimeError, match="predictions changed"):
        recovery.public_prechecks(private)


def test_public_prechecks_reject_reconstruction_hash_change(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "reconstruct_index_bytes", lambda: b"changed")
    with pytest.raises(RuntimeError, match="public reconstruction"):
        recovery.public_prechecks(private)


def test_private_gold_hash_is_checked_after_recovery_lock(monkeypatch, tmp_path):
    _, _, private, _, canonical, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    state = {"expected_gold_sha256": "0" * 64, "reconstructed_index_bytes": canonical, "reconstructed_index_rows": _rows()}
    with pytest.raises(RuntimeError, match="private gold SHA"):
        recovery._read_private_after_lock(private, state)


def test_public_prechecks_reject_existing_original_private_details(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    (private / "evaluation_details_v1").mkdir()
    with pytest.raises(RuntimeError, match="original evaluation output"):
        recovery.public_prechecks(private)


@pytest.mark.parametrize("name", [recovery.RECOVERY_LOCK_NAME, recovery.RECOVERY_METRICS_NAME, recovery.RECOVERY_MANIFEST_NAME])
def test_public_prechecks_reject_existing_recovery_artifact(monkeypatch, tmp_path, name):
    _, out, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    target = out / name
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="recovery artifact"):
        recovery.public_prechecks(private)


def test_public_prechecks_reject_existing_recovery_private_details(monkeypatch, tmp_path):
    _, _, private, _, _, _ = _setup_public_prechecks(monkeypatch, tmp_path)
    (private / recovery.RECOVERY_DETAILS_NAME).mkdir()
    with pytest.raises(RuntimeError, match="recovery artifact"):
        recovery.public_prechecks(private)


def test_recovery_lock_precedes_private_access(monkeypatch, tmp_path):
    events = []
    state = {"recovery_lock": tmp_path / "lock", "manifest_sha256": "m", "original_lock_sha256": "o", "private_root": tmp_path / "private"}
    monkeypatch.setattr(recovery, "public_prechecks", lambda _: events.append("public") or state)
    monkeypatch.setattr(recovery, "_atomic_recovery_lock", lambda *args, **kwargs: events.append("lock"))
    monkeypatch.setattr(recovery, "_read_private_after_lock", lambda *args: events.append("private") or (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        recovery.recover(tmp_path / "private")
    assert events == ["public", "lock", "private"]


def test_successful_synthetic_recovery_writes_only_recovery_outputs(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    out = root / "out"
    pred = out / "predictions"
    private = tmp_path / "private"
    root.mkdir()
    out.mkdir()
    pred.mkdir()
    private.mkdir()
    rows = _rows()
    canonical = _bytes(rows)
    (private / "gold_test_index.jsonl").write_bytes(canonical.replace(b"\n", b"\r\n"))
    (private / "gold_test.jsonl").write_text("".join(json.dumps({"ordinal": i}) + "\n" for i in range(240)), encoding="utf-8")
    (pred / "synthetic.jsonl").write_text(json.dumps({"query_id": "Q0a", "generation": {}}) + "\n", encoding="utf-8")
    protocol = root / "recovery.md"
    protocol.write_text("recovery", encoding="utf-8")
    state = {
        "recovery_lock": out / recovery.RECOVERY_LOCK_NAME,
        "manifest_sha256": "m" * 64,
        "original_lock_sha256": "o" * 64,
        "expected_gold_sha256": _expected((private / "gold_test.jsonl").read_bytes()),
        "expected_index_sha256": _expected(canonical),
        "reconstructed_index_bytes": canonical,
        "reconstructed_index_rows": rows,
        "private_root": private,
        "prediction_hashes": {"synthetic": "prediction"},
        "scoring_fingerprint": {"synthetic": True},
        "protocol_path": protocol,
    }
    monkeypatch.setattr(recovery, "public_prechecks", lambda _: state)
    monkeypatch.setattr(recovery, "EXPECTED_PRIVATE_INDEX_RAW_SHA256", _expected(canonical.replace(b"\n", b"\r\n")))
    monkeypatch.setattr(recovery.cli, "ROOT", root)
    monkeypatch.setattr(recovery.cli, "OUT", out)
    monkeypatch.setattr(recovery.cli, "PRED_OUT", pred)
    monkeypatch.setattr(recovery.cli, "METHODS", ("synthetic",))
    monkeypatch.setattr(recovery.cli, "queries", lambda: [{"query_id": "Q0a", "asset_id": "A"}])
    monkeypatch.setattr(recovery.cli, "retrieval_predictions", lambda: {"synthetic": [{"selected_evidence_ids": []}]})
    monkeypatch.setattr(recovery.cli, "validate_private_gold_objects", lambda *_: None)
    monkeypatch.setattr(recovery.cli, "scoring_fingerprint", lambda: state["scoring_fingerprint"])
    monkeypatch.setattr(recovery.cli, "evaluate_generation_prediction", lambda *args: {"task_success": 1.0})
    monkeypatch.setattr(recovery.cli, "macro_average", lambda rows: {"task_success": 1.0})
    monkeypatch.setattr(recovery.cli, "GENERATION_PROTOCOL_VERSION", "v1.9-exact-duplicate-root-field-suffix")
    metrics = recovery.recover(private)
    assert metrics == {"synthetic": {"task_success": 1.0}}
    assert (out / recovery.RECOVERY_METRICS_NAME).exists()
    assert (out / recovery.RECOVERY_MANIFEST_NAME).exists()
    assert (private / recovery.RECOVERY_DETAILS_NAME / "synthetic.jsonl").exists()
    assert not (out / "metrics.json").exists()
    assert not (out / "final_evaluation_manifest.json").exists()
    final = json.loads((out / recovery.RECOVERY_MANIFEST_NAME).read_text())
    assert final["status"] == "GENERATION_EVALUATION_COMPLETE_VIA_AUDITED_PRIVATE_INDEX_CRLF_RECOVERY"
    assert final["private_index_transport_equivalence"] == "exact_lf_to_crlf"
    assert final["scoring_evaluation_count"] == 1


def test_recovery_has_distinct_output_namespace_and_reuses_frozen_scoring():
    assert recovery.RECOVERY_PROTOCOL_VERSION == "private-index-crlf-recovery-v1"
    assert recovery.cli.evaluate_generation_prediction is not None
    assert recovery.cli.macro_average is not None
    assert recovery.RECOVERY_METRICS_NAME not in {"metrics.json", "final_evaluation_manifest.json"}


def test_original_outputs_and_locks_are_distinct():
    assert recovery.RECOVERY_LOCK_NAME != "evaluation_started.json"
    assert recovery.RECOVERY_METRICS_NAME != "metrics.json"
    assert recovery.RECOVERY_MANIFEST_NAME != "final_evaluation_manifest.json"
    assert recovery.RECOVERY_DETAILS_NAME != "evaluation_details_v1"


def test_recovery_source_does_not_modify_frozen_evaluator_files():
    source = Path(recovery.__file__).read_text(encoding="utf-8")
    assert "def evaluate_generation_prediction" not in source
    assert "def macro_average" not in source
