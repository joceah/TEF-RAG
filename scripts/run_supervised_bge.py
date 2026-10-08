"""Train and evaluate a document-only, task-adapted BGE reranker.

Train/selection never open test labels. The test action requires a sealed
checkpoint-selection manifest written by the validation action.
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

from scripts.run_tef_rag_v6_baseline_suite import public_evidence, public_queries
from scripts.evaluate_tef_rag_v6_public_retrieval import (
    _load_public_inputs, load_test_evaluator, validate_prediction_rows,
)
from tef_rag_v6.baseline_suite import bm25_rank
from tef_rag_v6.evaluation import average, evaluate_prediction

PUBLIC = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public"
OUT = ROOT / "results/v6/supervised_bge_reranker"
MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
SEED = 20261008


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_inputs(split, gold=True):
    queries = public_queries(rows(PUBLIC / f"queries_{split}.jsonl"))
    evidence = public_evidence(rows(PUBLIC / "evidence.jsonl"))
    labels = rows(PUBLIC / f"gold_{split}.jsonl") if gold else None
    if labels is not None and [x["query_id"] for x in queries] != [x["query_id"] for x in labels]:
        raise RuntimeError(f"{split} query/gold mismatch")
    return queries, evidence, labels


def positives(gold):
    # No relation, flow-edge, endpoint-pair or chain annotation is consumed.
    return {eid for group in gold["required_groups"] for eid in group["acceptable_evidence_ids"]}


def training_pairs(queries, evidence, gold, negatives_per_query):
    lookup = {row["evidence_id"]: row for row in evidence}
    pairs = []
    counts = {"positive": 0, "negative": 0, "queries_without_eligible_positive": 0}
    for query, label in zip(queries, gold):
        all_ranked = bm25_rank(query, evidence, 10_000)
        pool = all_ranked[:30]
        eligible = {row["evidence_id"] for row in all_ranked}
        pos = sorted(positives(label) & eligible)
        if not pos:
            counts["queries_without_eligible_positive"] += 1
        neg = [row["evidence_id"] for row in pool if row["evidence_id"] not in positives(label)][:negatives_per_query]
        qtext = query["query_text"]
        pairs.extend((qtext, lookup[eid]["text"], 1.0) for eid in pos)
        pairs.extend((qtext, lookup[eid]["text"], 0.0) for eid in neg)
        counts["positive"] += len(pos)
        counts["negative"] += len(neg)
    return pairs, counts


def install_lora(model, rank=8, alpha=16):
    import torch
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

        def forward(self, x):
            return self.base(x) + self.b(self.a(x)) * (alpha / rank)

    for param in model.parameters():
        param.requires_grad_(False)
    for layer in model.roberta.encoder.layer:
        attention = layer.attention.self
        attention.query = LoRALinear(attention.query)
        attention.value = LoRALinear(attention.value)
    for param in model.classifier.parameters():
        param.requires_grad_(True)
    return model


def make_model(model_path, checkpoint=None):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path, local_files_only=True, dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32
    )
    install_lora(model)
    if checkpoint:
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        missing, unexpected = model.load_state_dict(state, strict=False)
        allowed_missing = [name for name in missing if ".base." in name or (".a." not in name and ".b." not in name and not name.startswith("classifier."))]
        if unexpected or len(allowed_missing) != len(missing):
            raise RuntimeError(f"adapter state mismatch: {unexpected}, {set(missing)-set(allowed_missing)}")
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tokenizer


def adapter_state(model):
    return {name: value.detach().cpu() for name, value in model.state_dict().items()
            if ".a." in name or ".b." in name or name.startswith("classifier.")}


def predict_scores(model, tokenizer, pairs, batch_size=16):
    import torch
    scores = []
    model.eval()
    with torch.inference_mode():
        for begin in range(0, len(pairs), batch_size):
            batch = pairs[begin:begin + batch_size]
            encoded = tokenizer([p[0] for p in batch], [p[1] for p in batch],
                                padding=True, truncation=True, max_length=512, return_tensors="pt")
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            scores.extend(model(**encoded).logits.float().view(-1).cpu().tolist())
    return scores


def rank_split(model, tokenizer, queries, evidence):
    output = []
    for number, query in enumerate(queries, 1):
        candidates = bm25_rank(query, evidence, 30)
        scores = predict_scores(model, tokenizer, [(query["query_text"], row["text"]) for row in candidates])
        order = sorted(zip(candidates, scores), key=lambda pair: (-pair[1], -pair[0]["bm25_score"], pair[0]["evidence_id"]))
        output.append({"query_id": query["query_id"], "selected_evidence_ids": [row["evidence_id"] for row, _ in order[:5]], "relations": []})
        if number % 100 == 0:
            print(f"ranking: {number}/{len(queries)}", flush=True)
    return output


def metric(rows_, gold):
    return average([evaluate_prediction(pred, label) for pred, label in zip(rows_, gold)])


def train(args):
    import torch
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup
    torch.manual_seed(SEED)
    random.seed(SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    OUT.mkdir(parents=True, exist_ok=True)
    dev_q, evidence, dev_gold = split_inputs("development")
    val_q, _, val_gold = split_inputs("validation")
    pairs, counts = training_pairs(dev_q, evidence, dev_gold, args.negatives_per_query)
    rng = random.Random(SEED)
    rng.shuffle(pairs)
    model, tokenizer = make_model(args.model_path)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=args.learning_rate)
    steps = (len(pairs) + args.batch_size - 1) // args.batch_size * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, max(1, steps // 10), steps)
    loader = DataLoader(pairs, batch_size=args.batch_size, shuffle=False, collate_fn=lambda x: x)
    history = []
    best = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for index, batch in enumerate(loader, 1):
            encoded = tokenizer([x[0] for x in batch], [x[1] for x in batch],
                                padding=True, truncation=True, max_length=512, return_tensors="pt")
            encoded = {key: value.to(model.device) for key, value in encoded.items()}
            target = torch.tensor([x[2] for x in batch], device=model.device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=model.device.type == "cuda"):
                logits = model(**encoded).logits.float().view(-1)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_((p for p in model.parameters() if p.requires_grad), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(float(loss.detach()))
            if index % 100 == 0:
                print(f"epoch {epoch}: {index}/{len(loader)} batches, loss {sum(losses)/len(losses):.4f}", flush=True)
        predictions = rank_split(model, tokenizer, val_q, evidence)
        scores = metric(predictions, val_gold)
        checkpoint = OUT / f"checkpoint_epoch_{epoch}.pt"
        torch.save(adapter_state(model), checkpoint)
        record = {"epoch": epoch, "training_loss": sum(losses)/len(losses), "validation_metrics": scores,
                  "checkpoint": checkpoint.name, "checkpoint_sha256": sha(checkpoint)}
        history.append(record)
        save(OUT / "training_history.json", history)
        key = (scores["ndcg_at_5"], scores["recall_at_5"])
        if best is None or key > best[0]:
            best = (key, record)
            save(OUT / "validation_predictions.json", predictions)
            save(OUT / "validation_metrics.json", scores)
        print(f"epoch {epoch} validation nDCG@5={scores['ndcg_at_5']:.6f}, Recall@5={scores['recall_at_5']:.6f}", flush=True)
    manifest = {
        "model": MODEL, "revision": REVISION, "model_path": str(args.model_path),
        "model_config_sha256": sha(Path(args.model_path) / "config.json"),
        "model_weights_sha256": sha(Path(args.model_path) / "model.safetensors"),
        "split_counts": {"development": {"queries": len(dev_q), "chains": len(rows(PUBLIC / "chains_development.jsonl"))},
                         "validation": {"queries": len(val_q), "chains": len(rows(PUBLIC / "chains_validation.jsonl"))},
                         "test": {"queries": 480, "chains": 80}},
        "seed": SEED, "training": {"epochs": args.epochs, "learning_rate": args.learning_rate,
                                    "batch_size": args.batch_size, "max_length": 512, "lora_rank": 8,
                                    "lora_alpha": 16, "loss": "BCEWithLogits", "negative_sampling": "top BM25 false positives in eligible Top-30",
                                    "negatives_per_query": args.negatives_per_query, **counts},
        "selected_checkpoint": best[1], "selection_criterion": "validation nDCG@5, Recall@5 tie-breaker",
        "test_gold_accessed_before_selection": False,
    }
    save(OUT / "training_manifest.json", manifest)


def test(args):
    manifest = json.loads((OUT / "training_manifest.json").read_text(encoding="utf-8"))
    if sha(Path(args.model_path) / "config.json") != manifest["model_config_sha256"] or sha(Path(args.model_path) / "model.safetensors") != manifest["model_weights_sha256"]:
        raise RuntimeError("base BGE snapshot differs from training manifest")
    selected = manifest["selected_checkpoint"]
    checkpoint = OUT / selected["checkpoint"]
    if sha(checkpoint) != selected["checkpoint_sha256"]:
        raise RuntimeError("selected checkpoint hash mismatch")
    test_q, evidence, _ = split_inputs("test", gold=False)
    model, tokenizer = make_model(args.model_path, checkpoint)
    predictions = rank_split(model, tokenizer, test_q, evidence)
    gold_by_query, expected_ids, evaluator_hash = load_test_evaluator()
    query_by_id, evidence_by_id = _load_public_inputs(PUBLIC / "queries_test.jsonl", PUBLIC / "evidence.jsonl")
    validate_prediction_rows("supervised_bge_reranker", predictions, expected_ids, query_by_id, evidence_by_id)
    scores = metric(predictions, [gold_by_query[q["query_id"]] for q in test_q])
    save(OUT / "test_retrieval_predictions.json", predictions)
    save(OUT / "test_retrieval_metrics.json", {"metrics": scores, "test_evaluator_sha256": evaluator_hash,
                                               "prediction_sha256": sha(OUT / "test_retrieval_predictions.json")})
    print(json.dumps(scores, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("train", "test"))
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--negatives-per-query", type=int, default=4)
    args = parser.parse_args()
    if args.action == "train":
        train(args)
    else:
        test(args)


if __name__ == "__main__":
    main()
