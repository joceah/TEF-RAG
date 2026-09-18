import copy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sealed_preflight", ROOT / "scripts/preflight_tef_rag_v6_sealed_test.py"
)
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
MANIFEST = json.loads((ROOT / "results/v6/final_freeze_manifest.json").read_text(encoding="utf-8"))


def run_manifest(tmp_path, mutate):
    value = copy.deepcopy(MANIFEST)
    mutate(value)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return PREFLIGHT.verify(ROOT, path)[0]


@pytest.mark.parametrize(("mutation", "needle"), [
    (lambda x: x.__setitem__("tef_rag_method_commit", "0" * 40), "method_commit"),
    (lambda x: x["baselines"]["bge"].__setitem__("revision", "wrong"), "BGE"),
    (lambda x: x["baselines"]["ta_rag"].__setitem__("nomic_revision_or_local_hash", "sha256:wrong"), "Nomic"),
    (lambda x: x["baselines"]["ta_rag"].__setitem__("base_url", "http://127.0.0.1:55555"), "TA endpoint"),
    (lambda x: x["baselines"]["temporal_bm25"].__setitem__("lambda", 0.5), "lambda"),
    (lambda x: x["baselines"].__setitem__("top_k", 10), "top_k"),
])
def test_frozen_config_tampering_fails_closed(tmp_path, mutation, needle):
    assert any(needle in error for error in run_manifest(tmp_path, mutation))


def test_modified_result_artifact_hash_fails_closed(tmp_path, monkeypatch):
    for source in (
        "results/v6/baseline_suite", "results/v6/stage3d_nonlinear_ranknet",
        "artifacts/v6/stage3d_nonlinear_ranknet", "artifacts/v6/stage3a_pair_proposer",
    ):
        shutil.copytree(ROOT / source, tmp_path / source)
    shutil.copy2(ROOT / "results/v6/final_freeze_manifest.json", tmp_path / "results/v6/final_freeze_manifest.json")
    target = tmp_path / "data/generated/tef_v6_temporal_hard_benchmark_v1/metadata/validation_second_blind_review.json"
    target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/metadata/validation_second_blind_review.json", target)
    monkeypatch.setattr(PREFLIGHT.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    metric = tmp_path / "results/v6/baseline_suite/validation/metrics.json"
    metric.write_bytes(metric.read_bytes() + b"\n")
    errors, _ = PREFLIGHT.verify(tmp_path, tmp_path / "results/v6/final_freeze_manifest.json")
    assert "validation result artifact hash mismatch" in errors


def test_known_benchmark_issue_is_recorded_but_nonfatal():
    errors, warnings = PREFLIGHT.verify(ROOT, ROOT / "results/v6/final_freeze_manifest.json")
    assert not errors
    assert any("BENCHMARK_ISSUE_FOUND" in warning for warning in warnings)


def test_preflight_has_no_test_or_sealed_artifact_input_paths():
    source = (ROOT / "scripts/preflight_tef_rag_v6_sealed_test.py").read_text(encoding="utf-8")
    assert "gold_test" not in source
    assert "queries_test" not in source
    assert "sealed_evaluator" not in source
