"""Train and evaluate the task-adapted BGE reranker used in the paper.

Training uses development document-level relevance labels only. Validation
selects the checkpoint by nDCG@5 with Recall@5 as a tie-breaker. Test labels
are opened only after checkpoint selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_public_retrieval import TEST_EVALUATOR_SHA256, load_reference, visible
from tef_rag.baseline_suite import bm25_rank
from tef_rag.evaluation import average, evaluate_prediction

BENCHMARK = ROOT / "data/retrieval/benchmark"
OUT = ROOT / "results/fine_tuned_bge"
MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
SEED = 20261008


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_queries(source: list[dict]) -> list[dict]:
    fields = ("query_id", "query_text", "query_time", "asset_id", "asset_model", "asset_context")
    return [{key: row[key] for key in fields if key in row} for row in source]


def public_evidence(source: list[dict]) -> list[dict]:
    fields = (
        "evidence_id", "text", "event_time", "available_at", "asset_id", "asset_model",
        "event_type", "source_type", "valid_from", "valid_to", "withdrawn_at", "model_scope",
    )
    return [{key: row[key] for key in fields if key in row} for row in source]


def split_inputs(split: str, with_gold: bool = True):
    queries = public_queries(rows(BENCHMARK / f"queries_{split}.jsonl"))
    evidence = public_evidence(rows(BENCHMARK / "evidence.jsonl"))
    gold = rows(BENCHMARK / f"gold_{split}.jsonl") if with_gold else None
    if gold is not None and [row["query_id"] for row in queries] != [row["query_id"] for row in gold]:
        raise RuntimeError(f"{split} query/gold mismatch")
    return queries, evidence, gold


def positive_ids(gold: dict) -> set[str]:
    # Deliberately document-level only: no relation/flow labels are consumed.
    return {eid for group in gold["required_groups"] for eid in group["acceptable_evidence_ids"]}


def training_pairs(queries, evidence, gold, negatives_per_query: int):
    lookup = {row["evidence_id"]: row for row in evidence}
    pairs = []
    counts = {"positive": 0, "negative": 0, "queries_without_eligible_positive": 0}
    for query, label in zip(queries, gold):
        ranked = bm25_rank(query, evidence, 10_000)
        pool = ranked[:30]
        eligible = {row["evidence_id"] for row in ranked}
        positives = positive_ids(label)
        pos = sorted(positives & eligible)
        if not pos:
            counts["queries_without_eligible_positive"] += 1
        neg = [row["evidence_id"] for row in pool if row["evidence_id"] not in positives][:negatives_per_query]
        qtext = query["query_text"]
        pairs.extend((qtext, lookup[eid]["text"], 1.0) for eid in pos)
        pairs.extend((qtext, lookup[eid]["text"], 0.0) for eid in neg)
        counts["positive"] += len(pos)
        counts["negative"] += len(neg)
    return pairs, counts


def install_lora(model, rank: int = 8, alpha: int = 16):
    from torch import nn

    class LoRALinear(nn.Module):
        def __init__(self, base):
            super().__init__()
            self.base = base
            self.a = nn.Linear(base.in_features, rank, bias=False)
            self.b = nn.Linear(rank, base.out_features, bias=False)
            nn.init.kaiming_uniform_(self.a.weight, a=5 ** 0.5)
            nn.init.zeros_(self.b.weight)
            self.a.to(dtype=base.weight.dtype)
            self.b.to(dtype=base.weight.dtype)

        def forward(self, values):
            return self.base(values) + self.b(self.a(values)) * (alpha / rank)

    for parameter in model.parameters():
        parameter.requires_grad_(False)
    for layer in model.roberta.encoder.layer:
        attention = layer.attention.self
        attention.query = LoRALinear(attention.query)
        attention.value = LoRALinear(attention.value)
    for parameter in model.classifier.parameters():
        parameter.requires_grad_(True)
    return model


def make_model(model_path: Path, checkpoint: Path | None = None):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path,
        local_files_only=True,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )
    install_lora(model)
    if checkpoint is not None:
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        missing, unexpected = model.load_state_dict(state, strict=False)
        allowed_missing = [
            name for name in missing
            if ".base." in name or (".a." not in name and ".b." not in name and not name.startswith("classifier."))
        ]
        if unexpected or len(allowed_missing) != len(missing):
            raise RuntimeError("adapter checkpoint does not match the base reranker")
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tokenizer


def adapter_state(model):
    return {
        name: value.detach().cpu()
        for name, value in model.state_dict().items()
        if ".a." in name or ".b." in name or name.startswith("classifier.")
    }


def predict_scores(model, tokenizer, pairs, batch_size: int = 16):
    import torch

    scores = []
    model.eval()
    with torch.inference_mode():
        for begin in range(0, len(pairs), batch_size):
            batch = pairs[begin:begin + batch_size]
            encoded = tokenizer(
                [pair[0] for pair in batch],
                [pair[1] for pair in batch],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            scores.extend(model(**encoded).logits.float().view(-1).cpu().tolist())
    return scores


def rank_split(model, tokenizer, queries, evidence):
    output = []
    for number, query in enumerate(queries, 1):
        candidates = bm25_rank(query, evidence, 30)
        scores = predict_scores(model, tokenizer, [(query["query_text"], row["text"]) for row in candidates])
        ranked = sorted(
            zip(candidates, scores),
            key=lambda pair: (-pair[1], -pair[0]["bm25_score"], pair[0]["evidence_id"]),
        )
        output.append({
            "query_id": query["query_id"],
            "selected_evidence_ids": [row["evidence_id"] for row, _ in ranked[:5]],
            "relations": [],
        })
        if number % 100 == 0:
            print(f"ranking: {number}/{len(queries)}", flush=True)
    return output


def metrics(predictions, gold):
    return average([evaluate_prediction(prediction, label, 5) for prediction, label in zip(predictions, gold)])


def train(args):
    import torch
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup

    torch.manual_seed(SEED)
    random.seed(SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

    dev_queries, evidence, dev_gold = split_inputs("development")
    val_queries, _, val_gold = split_inputs("validation")
    pairs, counts = training_pairs(dev_queries, evidence, dev_gold, args.negatives_per_query)
    random.Random(SEED).shuffle(pairs)

    model, tokenizer = make_model(args.model_path)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.learning_rate)
    steps = ((len(pairs) + args.batch_size - 1) // args.batch_size) * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, max(1, steps // 10), steps)
    loader = DataLoader(pairs, batch_size=args.batch_size, shuffle=False, collate_fn=lambda batch: batch)

    OUT.mkdir(parents=True, exist_ok=True)
    history = []
    best = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in loader:
            encoded = tokenizer(
                [row[0] for row in batch], [row[1] for row in batch],
                padding=True, truncation=True, max_length=512, return_tensors="pt",
            )
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            target = torch.tensor([row[2] for row in batch], device=model.device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=model.device.type == "cuda"):
                logits = model(**encoded).logits.float().view(-1)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_((p for p in model.parameters() if p.requires_grad), 1.0)
            optimizer.step(); scheduler.step(); optimizer.zero_grad(set_to_none=True)
            losses.append(float(loss.detach()))

        predictions = rank_split(model, tokenizer, val_queries, evidence)
        score = metrics(predictions, val_gold)
        checkpoint = OUT / f"checkpoint_epoch_{epoch}.pt"
        torch.save(adapter_state(model), checkpoint)
        record = {
            "epoch": epoch,
            "training_loss": sum(losses) / len(losses),
            "validation_metrics": score,
            "checkpoint": checkpoint.name,
            "checkpoint_sha256": sha256(checkpoint),
        }
        history.append(record)
        key = (score["ndcg_at_5"], score["recall_at_5"])
        if best is None or key > best[0]:
            best = (key, record)
            save(OUT / "validation_predictions.json", predictions)
            save(OUT / "validation_metrics.json", score)
        save(OUT / "training_history.json", history)

    manifest = {
        "model": MODEL,
        "revision": REVISION,
        "model_config_sha256": sha256(args.model_path / "config.json"),
        "model_weights_sha256": sha256(args.model_path / "model.safetensors"),
        "split_counts": {"development_queries": len(dev_queries), "validation_queries": len(val_queries), "test_queries": 480},
        "seed": SEED,
        "training": {
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "batch_size": args.batch_size,
            "max_length": 512,
            "lora_rank": 8,
            "lora_alpha": 16,
            "loss": "BCEWithLogits",
            "negative_sampling": "highest-ranked BM25 false positives from the eligible Top-30",
            "negatives_per_query": args.negatives_per_query,
            **counts,
        },
        "selected_checkpoint": best[1],
        "selection_criterion": "validation nDCG@5, Recall@5 tie-breaker",
        "test_gold_accessed_before_selection": False,
    }
    save(OUT / "training_manifest.json", manifest)


def test(args):
    manifest = json.loads((OUT / "training_manifest.json").read_text(encoding="utf-8"))
    checkpoint = OUT / manifest["selected_checkpoint"]["checkpoint"]
    if sha256(checkpoint) != manifest["selected_checkpoint"]["checkpoint_sha256"]:
        raise RuntimeError("selected checkpoint hash mismatch")

    test_queries, evidence, _ = split_inputs("test", with_gold=False)
    model, tokenizer = make_model(args.model_path, checkpoint)
    predictions = rank_split(model, tokenizer, test_queries, evidence)

    raw_queries, expected_ids, gold_by_query = load_reference()
    if [row["query_id"] for row in predictions] != expected_ids:
        raise RuntimeError("test prediction coverage/order mismatch")
    raw_query_by_id = {row["query_id"]: row for row in raw_queries}
    evidence_by_id = {row["evidence_id"]: row for row in rows(BENCHMARK / "evidence.jsonl")}
    for prediction in predictions:
        selected = prediction["selected_evidence_ids"]
        if len(selected) > 5 or len(selected) != len(set(selected)):
            raise RuntimeError(f"invalid Top-5 output for {prediction['query_id']}")
        for evidence_id in selected:
            evidence_row = evidence_by_id.get(evidence_id)
            if evidence_row is None or not visible(evidence_row, raw_query_by_id[prediction["query_id"]]):
                raise RuntimeError(f"unavailable evidence {evidence_id} for {prediction['query_id']}")

    score = average([evaluate_prediction(row, gold_by_query[row["query_id"]], 5) for row in predictions])
    save(OUT / "test_retrieval_predictions.json", predictions)
    save(OUT / "test_retrieval_metrics.json", {
        "metrics": score,
        "test_evaluator_sha256": TEST_EVALUATOR_SHA256,
        "prediction_sha256": sha256(OUT / "test_retrieval_predictions.json"),
    })
    print(json.dumps(score, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("train", "test"))
    parser.add_argument("--model-path", type=Path, required=True, help="Local BAAI/bge-reranker-v2-m3 snapshot")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--negatives-per-query", type=int, default=4)
    args = parser.parse_args()
    train(args) if args.action == "train" else test(args)


if __name__ == "__main__":
    main()
