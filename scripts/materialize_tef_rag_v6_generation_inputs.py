"""Materialize released frozen retrieval predictions for the generation runner.

The generation runner historically reads ``results/v6/sealed_test``.  The
released prediction files live under ``data/retrieval``; this command verifies
their frozen hashes and byte-copies them into the ignored legacy location.
It performs no retrieval, model, or network work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/retrieval/frozen_test_predictions"
TARGET = ROOT / "results/v6/sealed_test"
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")
PREDICTION_MANIFEST_SHA256 = "995b9f739ad85f77f54977f357714438d9b425e76a5fea07b9022b767185ab7f"
PREDICTION_SHA256S = {
    "bm25": "e3fda5e21a2a43a1a7411fcdfd5e793c23b8da2474e78506f8257e1998ec681e",
    "bge_reranker": "a26acd912729a1a2aeff14c8334e78d4f84826cb19f5d22f5e22287fa8089c9a",
    "temporal_bm25": "9dee0253619896e50e2f6d7e74209b70733090366d816347702a5820912b7ba9",
    "ta_rag": "c35b66edfc94e0ea901368be899b77850af34cfd23ee9027423e5452b103fcc8",
    "tef_rag_stage3d": "b7d02bf95cdbe522a667e7e7772ec72f3925761f76157c3fa3c421896c383e76",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def materialize(source: Path = SOURCE, target: Path = TARGET) -> dict[str, str]:
    manifest = source / "prediction_manifest.json"
    if sha256(manifest) != PREDICTION_MANIFEST_SHA256:
        raise RuntimeError("published prediction manifest SHA mismatch")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for method in METHODS:
        path = source / f"{method}.json"
        if not path.exists() or sha256(path) != PREDICTION_SHA256S[method]:
            raise RuntimeError(f"published prediction SHA mismatch: {method}")
        entry = payload.get("predictions", {}).get(method, {})
        if entry.get("query_count") != 480 or entry.get("prediction_sha256") != PREDICTION_SHA256S[method]:
            raise RuntimeError(f"published prediction manifest entry mismatch: {method}")
    target_predictions = target / "predictions"
    target_predictions.mkdir(parents=True, exist_ok=True)
    for method in METHODS:
        shutil.copyfile(source / f"{method}.json", target_predictions / f"{method}.json")
    shutil.copyfile(manifest, target / "prediction_manifest.json")
    return {method: sha256(target_predictions / f"{method}.json") for method in METHODS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args()
    hashes = materialize(args.source, args.target)
    print(json.dumps({"target": str(args.target), "prediction_sha256s": hashes}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
