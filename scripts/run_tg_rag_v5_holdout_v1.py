"""Run pinned TG-RAG compatibility on one v5 holdout snapshot or finalize."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_tg_rag_complex_v2 as base


INPUT = ROOT / "experiments/runs/ta_tg_input_v5_holdout_v1"
FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_RAG_v5_holdout_v3_投影与排名预登记.md"
RUN = ROOT / "experiments/runs/tg_rag_v5_holdout_v1"

base.INPUT = INPUT
base.FREEZE = FREEZE
base.PLAN = PLAN
base.RUN = RUN


def main():
    base.main()
    completion_path = RUN / "completion.json"
    if completion_path.exists():
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        completion["dataset"] = "tef_v5_holdout_v3"
        completion["wrapper_sha256"] = base.sha(Path(__file__).resolve())
        completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
