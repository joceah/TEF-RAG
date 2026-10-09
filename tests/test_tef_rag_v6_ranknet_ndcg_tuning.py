import numpy as np
import pytest
import torch

from scripts.run_tef_rag_v6_ranknet_ndcg_tuning import validation_metrics
from tef_rag_v6.nonlinear_ranknet import RankNetMLP


def test_validation_empty_bank_uses_frozen_greedy_fallback():
    model = RankNetMLP(1)
    for parameter in model.parameters():
        torch.nn.init.zeros_(parameter)
    values = np.asarray([[1.0], [2.0]], dtype=np.float32)
    outcomes = np.asarray([[0.5, 0.4, 0.0, 0.0], [0.8, 0.7, 1.0, 1.0]], dtype=np.float32)
    fallback = np.asarray([[0.0, 0.0, 0.0, 0.0], [0.75, 0.65, 1.0, 1.0]], dtype=np.float32)
    metrics = validation_metrics(model, np.zeros(1, dtype=np.float32),
                                 np.ones(1, dtype=np.float32), values, outcomes,
                                 [0, 2, 2], fallback)
    assert metrics["recall_at_5"] == (0.5 + 0.75) / 2
    assert metrics["ndcg_at_5"] == pytest.approx(0.525)
    assert metrics["complete_at_5"] == 0.5
    assert metrics["flow_complete_at_5"] == 0.5
