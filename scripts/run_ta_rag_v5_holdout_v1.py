"""Run the fixed TA-RAG no-event-interval compatibility baseline on the v5 holdout."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_ta_rag_complex_v2 as base


INPUT = ROOT / "experiments/runs/ta_tg_input_v5_holdout_v1"
FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_RAG_v5_holdout_v3_投影与排名预登记.md"
RUN = ROOT / "experiments/runs/ta_rag_v5_holdout_v1"

base.RUN = RUN
base.base.INPUT = INPUT
base.base.FREEZE = FREEZE
base.base.PLAN = PLAN


def main():
    base.main()
    completion_path = RUN / "completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["input_hashes"][str(Path(__file__).resolve().relative_to(ROOT))] = base.base.sha(
        Path(__file__).resolve()
    )
    completion["dataset"] = "tef_v5_holdout_v3"
    completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
