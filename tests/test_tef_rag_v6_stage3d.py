import inspect, json, subprocess, sys
from pathlib import Path

import numpy as np
import pytest
import torch

from tef_rag_v6.nonlinear_ranknet import (NonlinearSetRanker, RankNetMLP,
    normalization_from_train, pairwise_ranknet_loss, rank_items)
from tef_rag_v6.set_scorer import BANK_VERSION


def test_pairwise_loss_prefers_positive_direction():
    model = RankNetMLP(1)
    for parameter in model.parameters(): parameter.data.zero_()
    model.network[-1].bias.data.fill_(0)
    base = pairwise_ranknet_loss(model, torch.tensor([[1.0]]), torch.tensor([[0.0]])).item()
    model.network[0].weight.data.fill_(1); model.network[2].weight.data.fill_(1)
    model.network[4].weight.data.fill_(1)
    improved = pairwise_ranknet_loss(model, torch.tensor([[1.0]]), torch.tensor([[0.0]])).item()
    assert improved < base


def test_hidden_sizes_config_and_legacy_checkpoint_compatibility(tmp_path):
    torch.manual_seed(123)
    default = RankNetMLP(3)
    torch.manual_seed(123)
    explicit = RankNetMLP(3, [64, 32])
    assert list(default.state_dict()) == list(explicit.state_dict())
    assert all(torch.equal(default.state_dict()[key], explicit.state_dict()[key])
               for key in default.state_dict())
    assert RankNetMLP(3, [128, 64, 32])(torch.zeros(2, 3)).shape == (2,)
    norm = tmp_path / "normalization.json"
    norm.write_text(json.dumps({"feature_names": ["a", "b", "c"],
                                "mean": [0, 0, 0], "std": [1, 1, 1]}))
    for hidden_sizes, metadata in (([64, 32], {"architecture": [3, 64, 32, 1]}),
                                   ([128, 64, 32], {"hidden_sizes": [128, 64, 32]})):
        path = tmp_path / f"model-{len(hidden_sizes)}.pt"
        original = RankNetMLP(3, hidden_sizes)
        NonlinearSetRanker(["a", "b", "c"], [0, 0, 0], [1, 1, 1],
                           original, metadata).save(path)
        loaded = NonlinearSetRanker.load(path, norm)
        assert list(loaded.model.state_dict()) == list(original.state_dict())
        assert loaded.utility({"a": 1.0}) == pytest.approx(
            NonlinearSetRanker(["a", "b", "c"], [0, 0, 0], [1, 1, 1],
                               original).utility({"a": 1.0}))


def test_normalization_uses_only_supplied_train_rows():
    train = np.asarray([[0.0, 2.0], [2.0, 4.0]], dtype=np.float32)
    mean, std = normalization_from_train(train)
    assert mean.tolist() == [1.0, 3.0]
    assert std.tolist() == [1.0, 1.0]


def test_inference_gold_free_and_deterministic_tie_break():
    model = RankNetMLP(1)
    for parameter in model.parameters(): parameter.data.zero_()
    scorer = NonlinearSetRanker(["x"], [0], [1], model)
    items = [{"ids": ("B",), "agnostic": {"x": 1}}, {"ids": ("A",), "agnostic": {"x": 2}}]
    assert rank_items(items, scorer)[0]["ids"] == ("A",)
    assert "gold" not in inspect.signature(scorer.utility).parameters


def test_candidate_bank_and_feature_schema_are_exact_stage3c():
    root = Path(__file__).parents[1]
    stage3c = json.loads((root / "artifacts/v6/stage3c_pairwise_ranker/feature_schema.json").read_text())
    assert BANK_VERSION == "stage3b-full5-top15-swap-v1"
    assert not any(name.startswith("relation=") for name in stage3c["agnostic_features"])


def test_freeze_tampering_http_and_no_test_split(tmp_path):
    from scripts.run_tef_rag_v6_stage3d import forbidden_http, verify_freeze
    with pytest.raises(RuntimeError, match="HTTP is forbidden"): forbidden_http()
    path = tmp_path / "model.pt"; path.write_bytes(b"model")
    with pytest.raises(RuntimeError, match="model_hash"):
        verify_freeze({"model_hash": "bad"}, {"model_hash": path}, only_paths=True)
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage3d.py"), "--split", "test"],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode != 0 and "invalid choice" in result.stderr
