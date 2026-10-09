"""Cache-only final-set-ranker tuning on development/validation, then one frozen test."""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from scripts.run_tef_rag_v6_stage3c import query_items
from scripts.run_tef_rag_v6_stage3d import make_pairs
from scripts.run_tef_rag_v6_stage3b import context, features_for, prediction_for
from tef_rag_v6 import LLMRelationClient, LLMRelationConfig, QueryConditionedRelationScorer, TEFRAGV6, V6Config, load_jsonl
from tef_rag_v6.evaluation import average, evaluate_prediction, group_coverage
from tef_rag_v6.nonlinear_ranknet import (NonlinearSetRanker, RankNetMLP, normalize,
    normalization_from_train, pairwise_ranknet_loss, rank_items, seed_everything, vectorize)
from tef_rag_v6.pair_proposal import LinearPairProposer
from tef_rag_v6.pairwise_ranker import deterministic_subsample, select_round0_negatives
from tef_rag_v6.set_scorer import BANK_VERSION
from scripts.run_tef_rag_v6_sealed_test import SEALED_SHA256

PRIOR = ROOT.parent / ".tef_v6_clean_baseline_935832"
CACHE = ROOT.parent / ".github_export/TEF-RAG/.cache/tef_rag_v6_llm_relation"
TEST_CACHE = ROOT.parent / ".github_export/TEF-RAG/.cache/tef_rag_v6_test_relation"
PUBLIC = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public"
SEALED = PUBLIC / "test_evaluator.jsonl"
OUT = ROOT / "results/v6/ranknet_ndcg_tuning"
ART = ROOT / "artifacts/v6/ranknet_ndcg_tuning"
MAT = OUT / "materialized"
SEED = 20260916
KEYS = ("recall_at_5", "ndcg_at_5", "complete_at_5", "flow_complete_at_5")
BASELINE = {"recall_at_5": 0.7566666666666666, "ndcg_at_5": 0.6885479556270926,
            "complete_at_5": 0.40625, "flow_complete_at_5": 0.4041666666666667}


def read(path): return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2); handle.write("\n")


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def endpoint_and_thinking():
    # Read only non-secret transport identity. No API key is used in this runner.
    values = {}
    for line in (ROOT.parent / "local.env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in {"ENDPOINT", "THINKING"}:
                values[key.strip()] = value.strip().strip("'\"")
    return values["ENDPOINT"], values.get("THINKING")


def forbidden_http(*_args, **_kwargs):
    raise RuntimeError("HTTP forbidden: relation cache miss")


def runtime(split="validation"):
    if split not in {"development", "validation", "test"}: raise ValueError(split)
    stage2a = read(ROOT / "configs/tef_rag_v6_stage2a_llm_relation.json")
    b1 = read(ROOT / "configs/tef_rag_v6_stage2b1_correction.json")
    config = V6Config.from_dict(read(ROOT / stage2a["pipeline_config"]))
    config = replace(config, search_pool_k=b1["search_pool_k"], **b1["beam"])
    endpoint, thinking = endpoint_and_thinking()
    relation = dict(stage2a["relation"])
    relation.update(endpoint=endpoint, model="deepseek-chat" if split == "test" else "deepseek-v4-flash",
                    thinking=None if split == "test" else thinking,
                    cache_dir=str(TEST_CACHE if split == "test" else CACHE))
    taxonomy = read(ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/metadata/relation_taxonomy.json")["relation_types"]
    client = LLMRelationClient(LLMRelationConfig.from_dict(relation), taxonomy,
                               api_key="not-used", transport=forbidden_http)
    original_load = client._load_cache
    def required_cache(fingerprint):
        value = original_load(fingerprint)
        if value is None: raise RuntimeError(f"frozen relation cache miss: {fingerprint}")
        return value
    client._load_cache = required_cache
    proposer_path = PRIOR / "artifacts/v6/stage3a_pair_proposer/model.json"
    if sha(proposer_path) != "a5329d2fdc56f022a25a57e7dc85eacc492a00703f1f3b7adef80bc07f07472a":
        raise RuntimeError("frozen proposer hash mismatch")
    proposer = LinearPairProposer.load(proposer_path)
    scorer = QueryConditionedRelationScorer(client, config.relation_threshold, proposer, pair_budget=32)
    retriever = TEFRAGV6(load_jsonl(PUBLIC / "evidence.jsonl"), config, relation_scorer=scorer)
    return retriever


def item_metrics(ids, gold, is_flow):
    covered, total = group_coverage(list(ids), gold)
    relevant = {eid for group in gold["required_groups"] for eid in group["acceptable_evidence_ids"]}
    dcg = sum(1 / math.log2(rank + 1) for rank, eid in enumerate(ids, 1) if eid in relevant)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(5, len(relevant)) + 1))
    return (covered / total if total else 0.0, dcg / ideal if ideal else 0.0,
            float(covered == total), float(is_flow))


def refined_pairs(items, metrics, limit=150):
    """Keep original flow preferences, add same-status nDCG distinctions."""
    positives = deterministic_subsample([item for item in items if item["flow_complete"]], 30)
    negatives = select_round0_negatives([item for item in items if not item["flow_complete"]], 30, 10)
    pairs = make_pairs(positives, negatives, cap=75)
    strata = {}
    for index, item in enumerate(items):
        key = (bool(item["flow_complete"]), bool(metrics[index][2]))
        strata.setdefault(key, []).append(index)
    for key in sorted(strata, reverse=True):
        indices = sorted(strata[key], key=lambda i: (metrics[i][1], items[i]["ids"]))
        low, high = indices[:12], indices[-12:][::-1]
        for offset, hi in enumerate(high):
            for lo in low[offset % 3::3]:
                if metrics[hi][1] - metrics[lo][1] >= 0.03:
                    pairs.append((items[hi]["agnostic"], items[lo]["agnostic"]))
                    if len(pairs) >= limit: return pairs
    return pairs


def materialize():
    if (MAT / "manifest.json").exists(): raise RuntimeError("materialization already exists")
    resume_development = (MAT / "development_pairs.npz").exists()
    feature_names = read(PRIOR / "artifacts/v6/stage3c_pairwise_ranker/feature_schema.json")["agnostic_features"]
    baseline_pos, baseline_neg, refined_pos, refined_neg = [], [], [], []
    val_features, val_metrics, val_fallback, offsets = [], [], [], [0]
    counts = Counter()
    if resume_development:
        prior_bank = read(PRIOR / "results/v6/stage3c_pairwise_set_ranker/candidate_bank_development.json")
        counts.update(development_queries=1440, development_cache_lookups=43746,
                      development_cache_hits=43746,
                      development_candidate_sets=round(prior_bank["mean_sets_per_query"] * 1440))
        existing = np.load(MAT / "development_pairs.npz")
        if any(existing[key].ndim != 2 or existing[key].shape[1] != len(feature_names)
               for key in existing.files):
            raise RuntimeError("partial development materialization is invalid")
    for split in (("validation",) if resume_development else ("development", "validation")):
        retriever = runtime(split)
        queries = load_jsonl(PUBLIC / f"queries_{split}.jsonl")
        gold = {row["query_id"]: row for row in load_jsonl(PUBLIC / f"gold_{split}.jsonl")}
        for index, query in enumerate(queries, 1):
            public, prediction, items = query_items(query, gold[query["query_id"]], retriever)
            diag = prediction["relation_diagnostics"]
            if diag["cache_lookup_count"] != diag["cache_hit_count"] or diag["request_count"]:
                raise RuntimeError("cache-only invariant failed")
            counts[f"{split}_cache_lookups"] += diag["cache_lookup_count"]
            counts[f"{split}_cache_hits"] += diag["cache_hit_count"]
            counts[f"{split}_queries"] += 1
            counts[f"{split}_candidate_sets"] += len(items)
            if split == "development":
                positives = deterministic_subsample([x for x in items if x["flow_complete"]], 30)
                negatives = select_round0_negatives([x for x in items if not x["flow_complete"]], 30, 10)
                base_pairs = make_pairs(positives, negatives, cap=150)
                metrics = [item_metrics(x["ids"], gold[query["query_id"]], x["flow_complete"]) for x in items]
                finer = refined_pairs(items, metrics)
                if base_pairs:
                    baseline_pos.append(vectorize([a for a, _ in base_pairs], feature_names))
                    baseline_neg.append(vectorize([b for _, b in base_pairs], feature_names))
                if finer:
                    refined_pos.append(vectorize([a for a, _ in finer], feature_names))
                    refined_neg.append(vectorize([b for _, b in finer], feature_names))
            else:
                val_features.append(vectorize([x["agnostic"] for x in items], feature_names)
                                    if items else np.empty((0, len(feature_names)), dtype=np.float32))
                val_metrics.append(np.asarray([item_metrics(x["ids"], gold[query["query_id"]], x["flow_complete"])
                                               for x in items], dtype=np.float32)
                                   if items else np.empty((0, 4), dtype=np.float32))
                base_metric = evaluate_prediction(prediction, gold[query["query_id"]], 5)
                val_fallback.append([base_metric[key] for key in KEYS])
                offsets.append(offsets[-1] + len(items))
            if index % 40 == 0:
                print(f"materialize {split}: {index}/{len(queries)}", flush=True)
    MAT.mkdir(parents=True, exist_ok=True)
    if not resume_development:
        np.savez_compressed(MAT / "development_pairs.npz",
                            baseline_positive=np.concatenate(baseline_pos),
                            baseline_negative=np.concatenate(baseline_neg),
                            refined_positive=np.concatenate(refined_pos),
                            refined_negative=np.concatenate(refined_neg))
    np.save(MAT / "validation_features.npy", np.concatenate(val_features))
    np.save(MAT / "validation_metrics.npy", np.concatenate(val_metrics))
    np.save(MAT / "validation_fallback_metrics.npy", np.asarray(val_fallback, dtype=np.float32))
    write(MAT / "validation_offsets.json", offsets)
    saved = np.load(MAT / "development_pairs.npz")
    manifest = {"feature_names": feature_names, "counts": dict(counts),
                "baseline_pair_count": len(saved["baseline_positive"]),
                "refined_pair_count": len(saved["refined_positive"]),
                "validation_candidate_count": offsets[-1], "bank_version": BANK_VERSION,
                "proposer_sha256": sha(PRIOR / "artifacts/v6/stage3a_pair_proposer/model.json"),
                "new_llm_calls": 0, "new_http_requests": 0}
    write(MAT / "manifest.json", manifest)
    print(json.dumps(manifest["counts"], indent=2), flush=True)


TRIALS = [
    {"id": "b64_adam_1e3", "objective": "flow_pairs", "hidden_sizes": [64, 32],
     "optimizer": "Adam", "learning_rate": 1e-3, "weight_decay": 1e-4, "batch_size": 512},
    {"id": "b128_adam_3e4", "objective": "flow_pairs", "hidden_sizes": [128, 64],
     "optimizer": "Adam", "learning_rate": 3e-4, "weight_decay": 0, "batch_size": 256},
    {"id": "b128deep_adamw_3e4", "objective": "flow_pairs", "hidden_sizes": [128, 64, 32],
     "optimizer": "AdamW", "learning_rate": 3e-4, "weight_decay": 1e-5, "batch_size": 256},
    {"id": "b256_adamw_1e4", "objective": "flow_pairs", "hidden_sizes": [256, 128, 64],
     "optimizer": "AdamW", "learning_rate": 1e-4, "weight_decay": 1e-4, "batch_size": 128},
    {"id": "r64_adamw_1e3", "objective": "flow_then_ndcg", "hidden_sizes": [64, 32],
     "optimizer": "AdamW", "learning_rate": 1e-3, "weight_decay": 1e-5, "batch_size": 512},
    {"id": "r128_adam_3e4", "objective": "flow_then_ndcg", "hidden_sizes": [128, 64],
     "optimizer": "Adam", "learning_rate": 3e-4, "weight_decay": 0, "batch_size": 256},
    {"id": "r128deep_adamw_3e4", "objective": "flow_then_ndcg", "hidden_sizes": [128, 64, 32],
     "optimizer": "AdamW", "learning_rate": 3e-4, "weight_decay": 1e-4, "batch_size": 256},
    {"id": "r256_adamw_1e4", "objective": "flow_then_ndcg", "hidden_sizes": [256, 128, 64],
     "optimizer": "AdamW", "learning_rate": 1e-4, "weight_decay": 1e-5, "batch_size": 128},
]


def validation_metrics(model, mean, std, values, outcomes, offsets, fallback):
    model.eval()
    scores = np.empty(len(values), dtype=np.float32)
    with torch.no_grad():
        for start in range(0, len(values), 16384):
            batch = normalize(np.asarray(values[start:start + 16384]), mean, std)
            scores[start:start + len(batch)] = model(torch.from_numpy(batch)).numpy()
    selected = [outcomes[int(np.argmax(scores[a:b])) + a] if b > a else fallback[index]
                for index, (a, b) in enumerate(zip(offsets[:-1], offsets[1:]))]
    result = np.mean(np.asarray(selected), axis=0, dtype=np.float64)
    return {name: float(value) for name, value in zip(KEYS, result)}


def pareto(rows):
    result = []
    for row in rows:
        metrics = row["validation_metrics"]
        if not any(all(other["validation_metrics"][key] >= metrics[key] for key in KEYS)
                   and any(other["validation_metrics"][key] > metrics[key] for key in KEYS)
                   for other in rows if other is not row):
            result.append(row["id"])
    return result


def tune():
    manifest = read(MAT / "manifest.json")
    feature_names = manifest["feature_names"]
    pairs = np.load(MAT / "development_pairs.npz")
    values = np.load(MAT / "validation_features.npy", mmap_mode="r")
    outcomes = np.load(MAT / "validation_metrics.npy", mmap_mode="r")
    fallback = np.load(MAT / "validation_fallback_metrics.npy", mmap_mode="r")
    offsets = read(MAT / "validation_offsets.json")
    mean, std = normalization_from_train(np.concatenate(
        [pairs["baseline_positive"], pairs["baseline_negative"]]))
    ART.mkdir(parents=True, exist_ok=True)
    norm_path = ART / "normalization.json"
    normalization = {"feature_names": feature_names, "mean": mean.tolist(), "std": std.tolist(),
                     "source": "development_flow_pairs_only"}
    if norm_path.exists() and read(norm_path) != normalization:
        raise RuntimeError("normalization changed during tuning")
    write(norm_path, normalization)
    original_model = PRIOR / "artifacts/v6/stage3d_nonlinear_ranknet/model.pt"
    original_norm = PRIOR / "artifacts/v6/stage3d_nonlinear_ranknet/normalization.json"
    original = NonlinearSetRanker.load(original_model, original_norm)
    baseline_metrics = validation_metrics(original.model, original.mean, original.std,
                                          values, outcomes, offsets, fallback)
    if any(abs(baseline_metrics[key] - BASELINE[key]) > 1e-5 for key in KEYS):
        raise RuntimeError(f"frozen upstream baseline reproduction failed: {baseline_metrics}")
    config = {"seed": SEED, "max_epochs": 12, "patience": 3, "primary": "validation nDCG@5",
              "set_metric_floor": {key: BASELINE[key] - 0.03 for key in
                                   ("recall_at_5", "complete_at_5", "flow_complete_at_5")},
              "objectives": {"flow_pairs": "existing Stage3D flow-complete positive versus negative",
                             "flow_then_ndcg": "75 original flow pairs plus up to 75 same-flow/same-complete nDCG-separated pairs per development query"},
              "trials": TRIALS, "baseline_validation": baseline_metrics}
    write(OUT / "tuning_config.json", config)
    trial_path = OUT / "validation_trials.json"
    records = read(trial_path) if trial_path.exists() else []
    completed = {row["id"] for row in records}
    torch.set_num_threads(min(4, torch.get_num_threads()))
    for trial in TRIALS:
        if trial["id"] in completed: continue
        prefix = "baseline" if trial["objective"] == "flow_pairs" else "refined"
        positive = torch.from_numpy(normalize(pairs[f"{prefix}_positive"], mean, std))
        negative = torch.from_numpy(normalize(pairs[f"{prefix}_negative"], mean, std))
        seed_everything(SEED)
        model = RankNetMLP(len(feature_names), trial["hidden_sizes"])
        optimizer_class = torch.optim.Adam if trial["optimizer"] == "Adam" else torch.optim.AdamW
        optimizer = optimizer_class(model.parameters(), lr=trial["learning_rate"],
                                    weight_decay=trial["weight_decay"])
        best_key, best_state, best_epoch, stale, history = None, None, 0, 0, []
        for epoch in range(1, config["max_epochs"] + 1):
            generator = torch.Generator().manual_seed(SEED + epoch)
            order = torch.randperm(len(positive), generator=generator)
            model.train(); total = 0.0
            for start in range(0, len(order), trial["batch_size"]):
                indices = order[start:start + trial["batch_size"]]
                optimizer.zero_grad()
                loss = pairwise_ranknet_loss(model, positive[indices], negative[indices])
                loss.backward(); optimizer.step()
                total += float(loss.item()) * len(indices)
            metrics = validation_metrics(model, mean, std, values, outcomes, offsets, fallback)
            history.append({"epoch": epoch, "train_loss": total / len(order), **metrics})
            key = tuple(metrics[name] for name in ("ndcg_at_5", "flow_complete_at_5",
                                                   "complete_at_5", "recall_at_5"))
            if best_key is None or key > best_key:
                best_key, best_state, best_epoch, stale = key, copy.deepcopy(model.state_dict()), epoch, 0
            else:
                stale += 1
            print(f"trial {trial['id']} epoch {epoch}: nDCG={metrics['ndcg_at_5']:.4f} flow={metrics['flow_complete_at_5']:.4f}", flush=True)
            if stale >= config["patience"]: break
        model.load_state_dict(best_state)
        metadata = {**trial, "seed": SEED, "best_epoch": best_epoch,
                    "architecture": [len(feature_names), *trial["hidden_sizes"], 1],
                    "pair_count": len(positive), "objective_label_source": "development_gold"}
        path = ART / "trials" / f"{trial['id']}.pt"
        NonlinearSetRanker(feature_names, mean, std, model, metadata).save(path)
        best_metrics = next(row for row in history if row["epoch"] == best_epoch)
        records.append({**trial, "best_epoch": best_epoch,
                        "validation_metrics": {key: best_metrics[key] for key in KEYS},
                        "epochs": history, "checkpoint": str(path.relative_to(ROOT))})
        write(trial_path, records)
        write(OUT / "pareto_frontier.json", pareto(
            [{"id": "original_stage3d", "validation_metrics": baseline_metrics}, *records]))
    rows = [{"id": "original_stage3d", "validation_metrics": baseline_metrics}, *records]
    floors = config["set_metric_floor"]
    admissible = [row for row in rows if all(row["validation_metrics"][key] >= floor
                                              for key, floor in floors.items())]
    selected = max(admissible, key=lambda row: tuple(row["validation_metrics"][key]
                                                    for key in ("ndcg_at_5", "flow_complete_at_5",
                                                                "complete_at_5", "recall_at_5")))
    selected_path = original_model if selected["id"] == "original_stage3d" else ROOT / selected["checkpoint"]
    shutil.copyfile(selected_path, ART / "model.pt")
    if selected["id"] == "original_stage3d":
        shutil.copyfile(original_norm, norm_path)
    frozen = {"selected": selected, "pareto_frontier": pareto(rows),
              "model_sha256": sha(ART / "model.pt"), "normalization_sha256": sha(norm_path),
              "validation_only_selection": True, "test_metric_seen": False,
              "new_llm_calls": 0, "new_http_requests": 0}
    write(OUT / "selection_frozen.json", frozen)
    print(json.dumps({"selected": selected, "pareto": frozen["pareto_frontier"]}, indent=2), flush=True)


def preflight_test():
    if not (OUT / "selection_frozen.json").exists():
        raise RuntimeError("model must be frozen before test cache preflight")
    scanner = subprocess.Popen(["rg", "--no-filename", "--color", "never", "-g", "*.json",
                                '"fingerprint"', str(TEST_CACHE)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    fingerprints = set()
    for line in scanner.stdout:
        try:
            value = json.loads(line)
            if value["judgment"].get("reason_code") != "client_failure_after_retries":
                fingerprints.add(value["fingerprint"])
        except (KeyError, ValueError):
            pass
    if scanner.wait() != 0: raise RuntimeError(scanner.stderr.read())
    retriever = runtime("test")
    queries = load_jsonl(PUBLIC / "queries_test.jsonl")
    if len(queries) != 480: raise RuntimeError("test query count mismatch")
    lookups = hits = 0
    missing = []
    for query in queries:
        public = retriever._public_query(query)
        eligible = [item for item in retriever.candidate_retrieval(public)
                    if retriever.temporal_eligibility(item["document"], public)[0]]
        scores = retriever._node_scores(public, eligible)
        pool = sorted(eligible, key=lambda item: (-scores[item["document"]["evidence_id"]]["total"],
                                                   item["document"]["evidence_id"]))[:retriever.config.search_pool_k]
        pairs, _ = retriever.relation_scorer.prefilter(pool, scores, retriever._relation_kind,
                                                       retriever._similarity, "learned", query=public)
        for pair in pairs:
            fingerprint = retriever.relation_scorer.client.fingerprint(public, pair["source"], pair["target"])
            lookups += 1
            if fingerprint in fingerprints: hits += 1
            elif len(missing) < 10:
                missing.append([query["query_id"], pair["source"]["evidence_id"],
                                pair["target"]["evidence_id"]])
    report = {"cache_path": str(TEST_CACHE), "query_count": len(queries),
              "lookups": lookups, "hits": hits, "misses": lookups - hits,
              "missing_examples": missing, "new_llm_calls": 0, "new_http_requests": 0}
    write(OUT / "test_cache_preflight.json", report)
    if hits != lookups: raise RuntimeError(f"test relation cache incomplete: {report}")
    print(json.dumps(report, indent=2), flush=True)


def final_test():
    frozen = read(OUT / "selection_frozen.json")
    preflight = read(OUT / "test_cache_preflight.json")
    if preflight["misses"]: raise RuntimeError("test cache incomplete")
    if sha(ART / "model.pt") != frozen["model_sha256"] or sha(ART / "normalization.json") != frozen["normalization_sha256"]:
        raise RuntimeError("selected checkpoint changed after validation selection")
    if (OUT / "test_metrics.json").exists(): raise RuntimeError("final test was already evaluated")
    scorer = NonlinearSetRanker.load(ART / "model.pt", ART / "normalization.json")
    retriever = runtime("test")
    queries = load_jsonl(PUBLIC / "queries_test.jsonl")
    progress_path = OUT / "test_progress.json"
    progress = read(progress_path) if progress_path.exists() else {"predictions": [], "cache_lookups": 0, "cache_hits": 0}
    rows = progress["predictions"]
    if [row["query_id"] for row in rows] != [query["query_id"] for query in queries[:len(rows)]]:
        raise RuntimeError("test progress query mismatch")
    for index in range(len(rows), len(queries)):
        query = queries[index]
        public, prediction, scores, demands, bank = context(query, retriever)
        diag = prediction["relation_diagnostics"]
        if diag["cache_hit_count"] != diag["cache_lookup_count"] or diag["request_count"]:
            raise RuntimeError("test cache-only invariant failed")
        progress["cache_lookups"] += diag["cache_lookup_count"]
        progress["cache_hits"] += diag["cache_hit_count"]
        if bank:
            items = []
            for ids in bank:
                aware, _ = features_for(ids, public, prediction, scores, demands, retriever, True)
                items.append({"ids": ids, "agnostic": {key: value for key, value in aware.items()
                                                        if not key.startswith("relation=")}})
            ids = rank_items(items, scorer)[0]["ids"]
        else:
            ids = tuple(prediction["selected_evidence_ids"])
        if len(ids) > 5 or any(not retriever.temporal_eligibility(retriever.by_id[eid], public)[0] for eid in ids):
            raise RuntimeError(f"invalid test evidence for {query['query_id']}")
        final = prediction_for(ids, {**prediction, "query_text": public["query_text"]}, retriever)
        rows.append({"query_id": query["query_id"], "selected_evidence_ids": final["selected_evidence_ids"],
                     "relations": final["relations"], "uncertainty": final["uncertainty"]})
        if (index + 1) % 20 == 0:
            write(progress_path, progress)
            print(f"final test prediction: {index + 1}/480", flush=True)
    write(progress_path, progress)
    write(OUT / "test_predictions.json", rows)
    if sha(SEALED) != SEALED_SHA256: raise RuntimeError("sealed evaluator hash mismatch")
    gold_rows = load_jsonl(SEALED)
    gold = {row["query"]["query_id"]: row["gold"] for row in gold_rows}
    if len(rows) != 480 or len(gold) != 480: raise RuntimeError("test query/gold count mismatch")
    result = average([evaluate_prediction(row, gold[row["query_id"]], 5) for row in rows])
    write(OUT / "test_metrics.json", result)
    write(OUT / "test_manifest.json", {"selected_model": frozen["selected"]["id"],
          "query_count": len(rows), "relation_cache_path": str(TEST_CACHE),
          "relation_cache_lookups": progress["cache_lookups"],
          "relation_cache_hits": progress["cache_hits"], "cache_misses": 0,
          "new_llm_calls": 0, "new_http_requests": 0,
          "prediction_sha256": sha(OUT / "test_predictions.json"),
          "sealed_evaluator_sha256": SEALED_SHA256,
          "fine_tuned_bge_ndcg_at_5": 0.6501,
          "original_tef_test": {"recall_at_5": 0.7228, "ndcg_at_5": 0.6231,
                                "complete_at_5": 0.3188, "flow_complete_at_5": 0.3146}})
    print(json.dumps(result, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("materialize", "tune", "preflight-test", "test"))
    args = parser.parse_args()
    if args.action == "materialize": materialize()
    if args.action == "tune": tune()
    if args.action == "preflight-test": preflight_test()
    if args.action == "test": final_test()


if __name__ == "__main__": main()
