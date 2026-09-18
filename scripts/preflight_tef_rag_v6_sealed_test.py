"""Fail-closed integrity checks before the first TEF-RAG v6 sealed evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "results/v6/final_freeze_manifest.json"

EXPECTED = {
    "tef_rag_method_commit": "49487cadb96efcbf7f4432965743a766575903d7",
    "benchmark_seal_commit": "4cd74c51bf874beac3c72df7fa64ae89f73438b8",
    "benchmark_protocol_commit": "b0e6e004378e7d7f29cabece1efa6b2c30489e9b",
    "baseline_protocol_commit": "e439621d2598fda2d2bc165b5679641e42a36321",
    "baseline_implementation_commit": "e756575cafafb6c2980377c6a8201aedbf4b4585",
    "baseline_results_commit": "79a6c164899b0d667c438a67f51cd84fcddd2058",
}
STAGE3D = {
    "model_sha256": "c25ee61ab7c7a72c226ba2523afa2319b31fe8cd02e362c3baf5c8db51e95220",
    "normalization_sha256": "ca1488cf48313aadb6bd781ca3371294a9393ccb0c30ef73a2b2908025c34312",
    "stage3a_proposer_sha256": "a5329d2fdc56f022a25a57e7dc85eacc492a00703f1f3b7adef80bc07f07472a",
    "relation_prompt_version": "tef-v6-stage2a-relation-v7",
    "candidate_bank_version": "stage3b-full5-top15-swap-v1",
}
BGE_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
NOMIC_HASH = "sha256:9e7d262b1fe5ea350782829496efa831901b77486bbde1cea54a4c822d010d5c"
TA_UPSTREAM = "9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    entries = []
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        entries.append(f"{item.relative_to(path).as_posix()}\0{sha256(item)}\n")
    return hashlib.sha256("".join(entries).encode()).hexdigest()


def check(errors: list[str], condition: bool, label: str) -> None:
    if not condition:
        errors.append(label)


def verify(root: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads((root / "results/v6/baseline_suite/baseline_freeze.json").read_text(encoding="utf-8"))
    stage = json.loads((root / "results/v6/stage3d_nonlinear_ranknet/development_freeze.json").read_text(encoding="utf-8"))

    for key, value in EXPECTED.items():
        check(errors, manifest.get(key) == value, f"wrong {key}")
        check(errors, baseline.get(key) == value, f"baseline freeze wrong {key}")
        resolved = subprocess.run(["git", "cat-file", "-e", f"{value}^{{commit}}"], cwd=root,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        check(errors, resolved.returncode == 0, f"missing commit {key}")
    baseline_payload = dict(baseline)
    baseline_hash = baseline_payload.pop("freeze_hash", "")
    canonical = json.dumps(baseline_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    check(errors, hashlib.sha256(canonical).hexdigest() == baseline_hash, "baseline freeze hash mismatch")

    frozen_stage = manifest.get("stage3d", {})
    for key, value in STAGE3D.items():
        check(errors, frozen_stage.get(key) == value, f"wrong Stage3D {key}")
    check(errors, sha256(root / "artifacts/v6/stage3d_nonlinear_ranknet/model.pt") == STAGE3D["model_sha256"], "Stage3D model hash mismatch")
    check(errors, sha256(root / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json") == STAGE3D["normalization_sha256"], "Stage3D normalization hash mismatch")
    check(errors, sha256(root / "artifacts/v6/stage3a_pair_proposer/model.json") == STAGE3D["stage3a_proposer_sha256"], "Stage3A proposer hash mismatch")
    check(errors, stage.get("model_hash") == STAGE3D["model_sha256"], "Stage3D freeze model hash mismatch")
    check(errors, stage.get("normalization_stats_hash") == STAGE3D["normalization_sha256"], "Stage3D freeze normalization hash mismatch")
    check(errors, stage.get("stage3a_proposer_model_hash") == STAGE3D["stage3a_proposer_sha256"], "Stage3D freeze proposer hash mismatch")
    check(errors, stage.get("relation_prompt_version") == STAGE3D["relation_prompt_version"], "relation prompt mismatch")
    check(errors, stage.get("candidate_bank_version") == STAGE3D["candidate_bank_version"], "candidate bank mismatch")

    configs = manifest.get("baselines", {})
    check(errors, configs.get("bm25") == {"k1": 1.5, "b": 0.75}, "BM25 config mismatch")
    bge = configs.get("bge", {})
    check(errors, bge == {"model": "BAAI/bge-reranker-v2-m3", "revision": BGE_REVISION, "candidate_depth": 30}, "BGE config mismatch")
    temporal = configs.get("temporal_bm25", {})
    check(errors, temporal.get("lambda") == 0.25, "Temporal-BM25 lambda mismatch")
    check(errors, temporal.get("lambda_candidates") == [0.25, 0.5, 0.75], "Temporal-BM25 candidates mismatch")
    check(errors, temporal.get("formula") == "lambda*normalized_bm25+(1-lambda)*temporal_score", "Temporal-BM25 formula mismatch")
    ta = configs.get("ta_rag", {})
    check(errors, ta.get("variant") == "official rerank variant", "TA-RAG variant mismatch")
    check(errors, ta.get("upstream_commit") == TA_UPSTREAM, "TA-RAG upstream mismatch")
    check(errors, ta.get("nomic_revision_or_local_hash") == NOMIC_HASH, "Nomic hash mismatch")
    nomic_weight = root / "experiments/runtime/models/nomic-embed-text-v1.5/model.safetensors"
    check(errors, nomic_weight.is_file() and f"sha256:{sha256(nomic_weight)}" == NOMIC_HASH,
          "local Nomic weight hash mismatch")
    check(errors, (ta.get("base_url"), ta.get("model"), ta.get("temperature")) == ("https://api.deepseek.com", "deepseek-chat", 0), "TA endpoint/model mismatch")
    check(errors, ta.get("api_key_persisted") is False, "TA API-key policy mismatch")
    check(errors, configs.get("top_k") == 5, "top_k mismatch")
    check(errors, baseline.get("bm25") == {"implementation": "tef_rag_v6.pipeline.BM25Index", "k1": 1.5, "b": 0.75}, "baseline freeze BM25 mismatch")
    check(errors, baseline.get("bge") == bge, "baseline freeze BGE mismatch")
    check(errors, baseline.get("temporal_bm25") == temporal, "baseline freeze Temporal-BM25 mismatch")
    check(errors, baseline.get("ta_rag") == ta, "baseline freeze TA-RAG mismatch")
    check(errors, baseline.get("top_k") == 5, "baseline freeze top_k mismatch")

    result_hashes = manifest.get("result_tree_sha256", {})
    for split in ("development", "validation"):
        check(errors, tree_hash(root / f"results/v6/baseline_suite/{split}") == result_hashes.get(split), f"{split} result artifact hash mismatch")
    marker = root / "results/v6/baseline_suite/validation/.formal_run_complete"
    check(errors, marker.is_file(), "baseline validation formal marker missing")
    check(errors, marker.is_file() and sha256(marker) == manifest.get("baseline_validation_formal_marker_sha256"), "baseline validation formal marker mismatch")

    issue = manifest.get("benchmark_issue", {})
    review = root / "data/generated/tef_v6_temporal_hard_benchmark_v1" / issue.get("path", "__missing__")
    actual_review_hash = sha256(review) if review.is_file() else ""
    recorded = (issue.get("status") == "BENCHMARK_ISSUE_FOUND" and not issue.get("fatal") and
                actual_review_hash == issue.get("actual_sha256") and
                issue.get("manifest_declared_sha256") == "00dc11c5b178c4ba774194a59e563032199640be9e47fd35c3edf6c13e608046")
    check(errors, recorded, "known benchmark validation-review mismatch not recorded correctly")
    if recorded:
        warnings.append("BENCHMARK_ISSUE_FOUND: known metadata bookkeeping mismatch (non-fatal)")

    isolation = manifest.get("isolation", {})
    check(errors, isolation == {"test_gold_accessed": False, "sealed_test_evaluator_accessed": False,
                                "private_test_artifact_accessed": False, "target_method_test_runs": 0},
          "test isolation declaration mismatch")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    errors, warnings = verify(ROOT, args.manifest.resolve())
    for warning in warnings:
        print(warning)
    if errors:
        print("FAIL CLOSED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PREFLIGHT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
