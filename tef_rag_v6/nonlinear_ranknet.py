"""Nonlinear RankNet used by TEF-RAG v6 Stage 3D."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn


class RankNetMLP(nn.Module):
    def __init__(self, input_dim, hidden_sizes=(64, 32)):
        super().__init__()
        hidden_sizes = tuple(hidden_sizes)
        if not hidden_sizes or any(not isinstance(size, int) or size <= 0 for size in hidden_sizes):
            raise ValueError("hidden_sizes must contain positive integers")
        layers = []
        width = input_dim
        for size in hidden_sizes:
            layers.extend((nn.Linear(width, size), nn.ReLU()))
            width = size
        layers.append(nn.Linear(width, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, values):
        return self.network(values).squeeze(-1)


def pairwise_ranknet_loss(model, positive, negative):
    logits = model(positive) - model(negative)
    return nn.functional.binary_cross_entropy_with_logits(logits, torch.ones_like(logits))


def vectorize(features, feature_names):
    return np.asarray([[row.get(name, 0.0) for name in feature_names] for row in features], dtype=np.float32)


def normalization_from_train(values):
    mean = values.mean(axis=0, dtype=np.float64).astype(np.float32)
    std = values.std(axis=0, dtype=np.float64).astype(np.float32)
    std[std < 1e-8] = 1.0
    return mean, std


def normalize(values, mean, std):
    return (values - mean) / std


def seed_everything(seed):
    np.random.seed(seed); torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


class NonlinearSetRanker:
    def __init__(self, feature_names, mean, std, model, metadata=None):
        self.feature_names = list(feature_names)
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)
        self.model = model.eval()
        self.metadata = metadata or {}

    def utility_many(self, rows):
        if not rows:
            return np.asarray([], dtype=np.float32)
        values = normalize(vectorize(rows, self.feature_names), self.mean, self.std)
        with torch.no_grad():
            return self.model(torch.from_numpy(values)).cpu().numpy()

    def utility(self, features):
        return float(self.utility_many([features])[0])

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        torch.save({"feature_names": self.feature_names, "state_dict": self.model.state_dict(),
                    "metadata": self.metadata}, path)

    @classmethod
    def load(cls, path, normalization_path):
        payload = torch.load(path, map_location="cpu", weights_only=True)
        norm = json.loads(Path(normalization_path).read_text(encoding="utf-8"))
        if payload["feature_names"] != norm["feature_names"]:
            raise RuntimeError("model/normalization feature schema mismatch")
        metadata = payload.get("metadata") or {}
        hidden_sizes = metadata.get("hidden_sizes")
        if hidden_sizes is None:
            architecture = metadata.get("architecture")
            hidden_sizes = architecture[1:-1] if architecture else (64, 32)
        model = RankNetMLP(len(payload["feature_names"]), hidden_sizes)
        model.load_state_dict(payload["state_dict"])
        return cls(payload["feature_names"], norm["mean"], norm["std"], model, metadata)


def rank_items(items, scorer):
    utilities = scorer.utility_many([item["agnostic"] for item in items])
    return [item for _, item in sorted(zip(utilities, items), key=lambda pair: (-float(pair[0]), pair[1]["ids"]))]
