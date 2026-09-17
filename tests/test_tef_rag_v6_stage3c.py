import inspect, json, subprocess, sys
from pathlib import Path

import pytest

from tef_rag_v6.pairwise_ranker import (LinearPairwiseSetRanker, construct_pairs,
    deterministic_subsample, mirrored_examples, rank_items, select_mined_negatives)
from tef_rag_v6.set_scorer import BANK_VERSION, candidate_bank


def item(query, ids, value, flow=False, hand=0):
    return {"query_id": query, "ids": tuple(ids), "agnostic": {"x": value},
            "aware": {"x": value, "relation=updates:count": value},
            "flow_complete": flow, "hand_score": hand, "hardness": hand}


def test_pair_direction_mirror_same_query_deterministic_and_cap():
    positives = [item("q", "ABCDE", 3, True), item("q", "ABCDF", 2, True)]
    negatives = [item("q", f"ABCD{x}", i, False, i) for i, x in enumerate("GHIJKL")]
    pairs = construct_pairs("q", positives, negatives, "agnostic", max_pairs=4)
    assert pairs == construct_pairs("q", positives, negatives, "agnostic", max_pairs=4)
    assert len(pairs) == 4 and pairs[0]["delta"]["x"] == 3 - 5
    rows, labels = mirrored_examples(pairs)
    assert labels[:2] == [1, 0] and rows[1]["x"] == -rows[0]["x"]
    with pytest.raises(ValueError):
        construct_pairs("q", positives, [item("other", "ABCDE", 0)], "agnostic")


def test_positive_subsample_is_even_and_deterministic():
    values = [item("q", f"A{i:04d}", i, True) for i in range(100)]
    chosen = deterministic_subsample(values, 30)
    assert chosen == deterministic_subsample(values, 30) and len(chosen) == 30
    assert chosen[0]["ids"] == values[0]["ids"] and chosen[-1]["ids"] == values[-1]["ids"]


def test_mining_uses_highest_ranked_false_positives_deterministically():
    scorer = LinearPairwiseSetRanker(["x"], [1.0], {})
    negatives = [item("q", f"N{i:04d}", i, False, i / 10) for i in range(25)]
    selected = select_mined_negatives(negatives, scorer, False, model_limit=2, hand_limit=0)
    assert [x["agnostic"]["x"] for x in selected] == [24, 23]
    assert all(not x["flow_complete"] for x in selected)


def test_ranker_gold_free_tie_break_and_feature_ablation():
    scorer = LinearPairwiseSetRanker(["x"], [1], {})
    values = [item("q", "BCDEF", 1), item("q", "ABCDE", 1)]
    assert rank_items(values, scorer, "agnostic")[0]["ids"] == tuple("ABCDE")
    assert "gold" not in inspect.signature(scorer.utility).parameters
    assert not any(name.startswith("relation=") for name in values[0]["agnostic"])
    assert any(name.startswith("relation=") for name in values[0]["aware"])


def test_positive_hit_one_includes_frozen_greedy_fallback():
    from scripts.run_tef_rag_v6_stage3c import positive_rank_metrics
    metrics = positive_rank_metrics([1, 3, None], 3, fallback_positive_count=1)
    assert metrics["positive_set_hit_at_1"] == 2 / 3


def test_candidate_bank_is_exact_frozen_stage3b_bank():
    assert BANK_VERSION == "stage3b-full5-top15-swap-v1"
    ids = [f"E{i:02d}" for i in range(30)]
    scores = {value: {"total": 30-index} for index, value in enumerate(ids)}
    greedy = ids[:4] + [ids[20]]
    bank = candidate_bank(ids, scores, greedy, ids[1:6], top_m=15, final_k=5)
    assert bank == candidate_bank(ids, scores, greedy, ids[1:6], top_m=15, final_k=5)
    assert tuple(sorted(greedy)) in bank and len(bank) == len(set(bank))
    assert all(len(value) == 5 for value in bank)
    assert "gold" not in inspect.signature(candidate_bank).parameters


def test_freeze_tampering_is_rejected(tmp_path):
    from scripts.run_tef_rag_v6_stage3c import verify_freeze
    model = tmp_path / "model.json"; model.write_text("{}", encoding="utf-8")
    freeze = {"selected_ranker_model_hash": "bad"}
    with pytest.raises(RuntimeError, match="selected_ranker_model_hash"):
        verify_freeze(freeze, {"selected_ranker_model_hash": model}, only_paths=True)


def test_http_fail_closed_one_round_and_no_test_split():
    from scripts.run_tef_rag_v6_stage3c import forbidden_http
    with pytest.raises(RuntimeError, match="HTTP is forbidden"):
        forbidden_http()
    config = json.loads((Path(__file__).parents[1] / "configs/tef_rag_v6_stage3c_pairwise_set_ranker.json").read_text())
    assert config["hard_negative_rounds"] == 1
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage3c.py"), "--split", "test"],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode != 0 and "invalid choice" in result.stderr
