"""Freeze the self-generated holdout before any retrieval or ranking."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/tef_v5_holdout_v3"
GENERATION = ROOT / "experiments/runs/tef_v5_holdout_v3_generation/completion.json"
PLAN_V1 = ROOT / "plans/TEF_RAG_v5_holdout_v1_生成与协议变更.md"
PLAN_V2 = ROOT / "plans/TEF_RAG_v5_holdout_v2_生成接口修正.md"
PLAN_V3 = ROOT / "plans/TEF_RAG_v5_holdout_v3_旧规程生效起点补全.md"
FAILURE_V1 = ROOT / "experiments/runs/tef_v5_holdout_v1_generation/attempts.json"
FAILURE_V2 = ROOT / "experiments/runs/tef_v5_holdout_v2_generation/attempts.json"
OUT = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    manifest = read(DATA / "manifest.json")
    if manifest.get("status") != "self_generated_unreviewed_candidate":
        raise RuntimeError("unexpected candidate status")
    if manifest.get("ranking_run") or manifest.get("independent_human_review") is not False:
        raise RuntimeError("candidate review/ranking state is incompatible with this freeze")
    if (manifest.get("cases"), manifest.get("records"), manifest.get("queries")) != (4, 48, 16):
        raise RuntimeError("candidate counts differ from preregistration")
    for relative, expected in manifest["output_hashes"].items():
        if sha(DATA / relative) != expected:
            raise RuntimeError(f"dataset hash mismatch: {relative}")
    if read(GENERATION) != manifest:
        raise RuntimeError("generation completion and dataset manifest differ")

    files = [
        DATA / "manifest.json",
        DATA / "assets.json",
        DATA / "evidence.jsonl",
        DATA / "queries.jsonl",
        DATA / "evaluation/gold.jsonl",
        DATA / "evaluation/review.md",
        DATA / "authoring/blueprints.jsonl",
        GENERATION,
        PLAN_V1,
        PLAN_V2,
        PLAN_V3,
        FAILURE_V1,
        FAILURE_V2,
    ]
    result = {
        "status": "self_generated_holdout_frozen_without_independent_review",
        "dataset": "tef_v5_holdout_v3",
        "ranking_run_before_freeze": False,
        "independent_human_review": False,
        "protocol_change_authorized_by_user": True,
        "cases": 4,
        "records": 48,
        "queries": 16,
        "generation_model_responses_in_selected_sources": 5,
        "generation_selected_source_usage": manifest["usage"],
        "all_generation_attempt_model_responses": 7,
        "all_generation_attempt_total_tokens": 44161,
        "hashes": {str(path.relative_to(ROOT)): sha(path) for path in files},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and read(OUT) != result:
        raise RuntimeError("refusing to overwrite a different freeze manifest")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
