"""Run the final TEF-RAG v6 method experiment: a fixed nonlinear RankNet."""
from __future__ import annotations

import argparse, copy, hashlib, json, platform, statistics, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage3a import digest, group_split
from scripts.run_tef_rag_v6_stage3c import query_items, runtime as stage3c_runtime
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete
from tef_rag_v6.nonlinear_ranknet import (NonlinearSetRanker, RankNetMLP, normalize,
    normalization_from_train, pairwise_ranknet_loss, rank_items, seed_everything, vectorize)
from tef_rag_v6.pairwise_ranker import deterministic_subsample, select_round0_negatives
from scripts.run_tef_rag_v6_stage3b import prediction_for
from tef_rag_v6.set_scorer import BANK_VERSION

DEFAULT_CONFIG = ROOT / "configs/tef_rag_v6_stage3d_nonlinear_ranknet.json"
EXPECTED_SPLIT_HASH = "5eaff9f55889dcb07386f24b7da6684e658330010768bed73ada7a0c69e15811"


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def forbidden_http(*args, **kwargs): raise RuntimeError("Stage3D cache miss: HTTP is forbidden")


def runtime(raw):
    stage3c = json.loads((ROOT / raw["stage3c_config"]).read_text(encoding="utf-8"))
    stage3b, stage3a, stage3a_freeze, client, retriever = stage3c_runtime(stage3c)
    client.transport = forbidden_http
    stage3c_freeze = json.loads((ROOT / stage3c["output_dir"] / "development_freeze.json").read_text(encoding="utf-8"))
    schema_path = ROOT / stage3c["artifact_dir"] / "feature_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    checks = {"base_stage3c_commit": raw["base_stage3c_commit"], "candidate_bank_version": BANK_VERSION,
        "feature_schema_hash": digest(schema), "group_split_hash": stage3c_freeze["group_split_hash"],
        "stage3a_proposer_model_hash": stage3a_freeze["model_sha256"],
        "stage3a_pair_budget": retriever.relation_scorer.pair_budget,
        "relation_prompt_version": stage3a_freeze["relation_prompt_version"], "seed": raw["seed"]}
    expected = {"base_stage3c_commit": "0d8c2031ff57c82f48ef0a8d2747659bf979e569",
        "candidate_bank_version": "stage3b-full5-top15-swap-v1",
        "feature_schema_hash": stage3c_freeze["feature_schema_hash"],
        "group_split_hash": EXPECTED_SPLIT_HASH,
        "stage3a_proposer_model_hash": stage3c_freeze["stage3a_proposer_model_hash"],
        "stage3a_pair_budget": 32, "relation_prompt_version": "tef-v6-stage2a-relation-v7", "seed": 20260916}
    for key, value in expected.items():
        if checks[key] != value: raise RuntimeError(f"frozen dependency mismatch: {key}")
    return stage3c, stage3c_freeze, stage3a_freeze, client, retriever, schema


def select_r1_negatives(negatives, scorer, model_limit=20, hand_limit=10):
    if not negatives: return []
    utilities = scorer.utility_many([item["agnostic"] for item in negatives])
    ranked = [item for _, item in sorted(zip(utilities, negatives),
              key=lambda pair: (-float(pair[0]), pair[1]["ids"]))]
    hand = sorted(negatives, key=lambda item: (-item["hand_score"], item["ids"]))[:hand_limit]
    return list({item["ids"]: item for item in ranked[:model_limit] + hand}.values())


def make_pairs(positives, negatives, cap=150):
    pairs = []
    for positive_index, positive in enumerate(positives):
        if not negatives: break
        for offset in range(min(5, len(negatives))):
            negative = negatives[(positive_index + offset) % len(negatives)]
            pairs.append((positive["agnostic"], negative["agnostic"]))
            if len(pairs) >= cap: return pairs
    return pairs


def prepare_pairs(queries, gold, retriever, groups, round0=None):
    pairs = []; stats = Counter(); sizes = []; started = time.perf_counter()
    for index, query in enumerate(queries, 1):
        if str(query["chain_id"]) not in groups: continue
        _, _, items = query_items(query, gold[query["query_id"]], retriever)
        positives = deterministic_subsample([item for item in items if item["flow_complete"]], 30)
        negatives = [item for item in items if not item["flow_complete"]]
        sizes.append(len(items)); stats["queries"] += 1
        if not positives:
            stats["queries_without_positive_bank_set"] += 1; continue
        stats["queries_with_positive_bank_set"] += 1
        chosen = (select_round0_negatives(negatives, 30, 10) if round0 is None
                  else select_r1_negatives(negatives, round0, 20, 10))
        query_pairs = make_pairs(positives, chosen)
        pairs.extend(query_pairs); stats["ranking_pairs"] += len(query_pairs)
        if index % 80 == 0: print(f"pair construction: {index}/{len(queries)}", flush=True)
    stats.update(candidate_sets=sum(sizes), mean_sets_per_query=statistics.mean(sizes),
                 runtime_seconds=time.perf_counter()-started)
    return pairs, dict(stats)


def fit(pairs, feature_names, mean, std, raw, round_name, scope):
    positives = normalize(vectorize([pair[0] for pair in pairs], feature_names), mean, std)
    negatives = normalize(vectorize([pair[1] for pair in pairs], feature_names), mean, std)
    dataset = TensorDataset(torch.from_numpy(positives), torch.from_numpy(negatives))
    seed_everything(raw["seed"])
    model = RankNetMLP(len(feature_names))
    optimizer = torch.optim.Adam(model.parameters(), lr=raw["learning_rate"], weight_decay=raw["weight_decay"])
    best_loss, best_state, stale, history = float("inf"), None, 0, []
    for epoch in range(raw["max_epochs"]):
        generator = torch.Generator().manual_seed(raw["seed"] + epoch)
        loader = DataLoader(dataset, batch_size=raw["batch_size"], shuffle=True, generator=generator)
        total = 0.0; count = 0; model.train()
        for positive, negative in loader:
            optimizer.zero_grad(); loss = pairwise_ranknet_loss(model, positive, negative)
            loss.backward(); optimizer.step()
            total += float(loss.item()) * len(positive); count += len(positive)
        epoch_loss = total / count; history.append(epoch_loss)
        if epoch_loss < best_loss - 1e-7:
            best_loss = epoch_loss; best_state = copy.deepcopy(model.state_dict()); stale = 0
        else:
            stale += 1
            if stale >= raw["early_stopping_patience"]: break
    model.load_state_dict(best_state)
    metadata = {"architecture": [len(feature_names), 64, 32, 1], "objective": "BCEWithLogits(score_positive-score_negative,1)",
        "optimizer": "Adam", "round": round_name, "scope": scope, "epochs": len(history),
        "best_train_loss": best_loss, "train_loss_history": history, "pair_count": len(pairs), "seed": raw["seed"]}
    return NonlinearSetRanker(feature_names, mean, std, model, metadata)


def rank_diagnostics(ranks, query_count, fallback):
    available = [rank for rank in ranks if rank is not None]
    output = {f"positive_set_hit_at_{cutoff}": (fallback + sum(rank is not None and rank <= cutoff for rank in ranks))/query_count
              for cutoff in (1, 3, 5, 10)}
    output.update(bank_oracle_queries=len(available), bank_oracle_fraction=len(available)/query_count)
    if available:
        output.update(mean_best_positive_rank=float(np.mean(available)), median_best_positive_rank=float(np.median(available)),
                      p75_best_positive_rank=float(np.percentile(available, 75)), p90_best_positive_rank=float(np.percentile(available, 90)))
    return output


def evaluate(queries, gold, retriever, rankers):
    metrics = {"stage3a_greedy": []} | {name: [] for name in rankers}
    ranks = {name: [] for name in rankers}; fallback = Counter(); cache = Counter()
    for index, query in enumerate(queries, 1):
        public, prediction, items = query_items(query, gold[query["query_id"]], retriever)
        diag = prediction["relation_diagnostics"]; cache.update(lookups=diag["cache_lookup_count"], hits=diag["cache_hit_count"])
        base = {**prediction, "query_text": public["query_text"]}
        metrics["stage3a_greedy"].append(evaluate_prediction(prediction, gold[query["query_id"]], 5))
        for name, scorer in rankers.items():
            if not items:
                ids = tuple(prediction["selected_evidence_ids"]); ranks[name].append(None)
                fallback[name] += int(flow_complete(list(ids), gold[query["query_id"]]))
            else:
                ranked = rank_items(items, scorer); ids = ranked[0]["ids"]
                ranks[name].append(next((position for position, item in enumerate(ranked, 1) if item["flow_complete"]), None))
            metrics[name].append(evaluate_prediction(prediction_for(ids, base, retriever), gold[query["query_id"]], 5))
        if index % 20 == 0 or index == len(queries): print(f"ranking evaluation: {index}/{len(queries)}", flush=True)
    return ({name: average(rows) for name, rows in metrics.items()},
            {name: rank_diagnostics(value, len(queries), fallback[name]) for name, value in ranks.items()},
            {"relation_cache_lookups": cache["lookups"], "cache_hits": cache["hits"],
             "cache_hit_rate": cache["hits"]/cache["lookups"], "new_llm_calls": 0, "new_http_requests": 0})


def verify_freeze(freeze, current, only_paths=False):
    for key, value in current.items():
        actual = sha256(value) if isinstance(value, Path) else value
        if freeze.get(key) != actual: raise RuntimeError(f"freeze mismatch: {key}")
    if only_paths: return True
    required = ("base_stage3c_commit", "stage3a_proposer_model_hash", "stage3a_pair_budget", "candidate_bank_version",
        "feature_schema_hash", "normalization_stats_hash", "model_hash", "group_split_hash", "relation_prompt_version", "seed")
    if any(key not in freeze for key in required): raise RuntimeError("incomplete Stage3D freeze")
    return True


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--split", choices=("development", "validation"), default="development"); args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    stage3c, stage3c_freeze, stage3a_freeze, client, retriever, schema = runtime(raw)
    output, artifact = ROOT/raw["output_dir"], ROOT/raw["artifact_dir"]
    queries, gold = load_inputs(args.split); freeze_path = output/"development_freeze.json"
    feature_names = schema["agnostic_features"]
    if args.split == "development":
        train_groups, tune_groups = group_split(queries, raw["seed"])
        split_hash = digest({"train": sorted(train_groups), "tune": sorted(tune_groups)})
        if split_hash != EXPECTED_SPLIT_HASH: raise RuntimeError("grouped split mismatch")
        checkpoint_model = artifact/"_development_r0.pt"; checkpoint_norm = artifact/"_development_norm.json"
        checkpoint_stats = artifact/"_development_r0_stats.json"
        if checkpoint_model.exists() and checkpoint_norm.exists() and checkpoint_stats.exists():
            norm = json.loads(checkpoint_norm.read_text(encoding="utf-8")); mean = np.asarray(norm["mean"], dtype=np.float32)
            std = np.asarray(norm["std"], dtype=np.float32); r0 = NonlinearSetRanker.load(checkpoint_model, checkpoint_norm)
            r0_stats = json.loads(checkpoint_stats.read_text(encoding="utf-8"))
        else:
            r0_pairs, r0_stats = prepare_pairs(queries, gold, retriever, train_groups)
            normalization_values = vectorize([row for pair in r0_pairs for row in pair], feature_names)
            mean, std = normalization_from_train(normalization_values)
            r0 = fit(r0_pairs, feature_names, mean, std, raw, "round0", "development_train")
            artifact.mkdir(parents=True, exist_ok=True); r0.save(checkpoint_model)
            write_json(checkpoint_norm, {"feature_names": feature_names, "mean": mean.tolist(), "std": std.tolist()})
            write_json(checkpoint_stats, r0_stats)
        r1_pairs, r1_stats = prepare_pairs(queries, gold, retriever, train_groups, r0)
        r1 = fit(r1_pairs, feature_names, mean, std, raw, "round1", "development_train")
        tune_queries = [query for query in queries if str(query["chain_id"]) in tune_groups]
        tune_metrics, tune_ranks, tune_cache = evaluate(tune_queries, gold, retriever, {"mlp_r0": r0, "mlp_r1": r1})
        stage3c_metrics = json.loads((ROOT/stage3c["output_dir"]/"ranking_metrics_development.json").read_text(encoding="utf-8"))
        tune_metrics["stage3a_greedy"] = stage3c_metrics["stage3a_greedy"]
        tune_metrics["stage3c_linear_r1"] = stage3c_metrics["pairwise_agnostic_r1"]
        selected = max(("mlp_r0", "mlp_r1"), key=lambda name: (tune_metrics[name]["flow_complete_at_5"],
            tune_metrics[name]["complete_at_5"], tune_metrics[name]["recall_at_5"], tune_metrics[name]["ndcg_at_5"], name))
        all_groups = train_groups | tune_groups
        full_r0_pairs, full_r0_stats = prepare_pairs(queries, gold, retriever, all_groups)
        full_r0 = fit(full_r0_pairs, feature_names, mean, std, raw, "round0", "all_development")
        if selected == "mlp_r1":
            full_selected_pairs, full_selected_stats = prepare_pairs(queries, gold, retriever, all_groups, full_r0)
            frozen = fit(full_selected_pairs, feature_names, mean, std, raw, "round1", "all_development")
        else:
            full_selected_pairs, full_selected_stats, frozen = full_r0_pairs, full_r0_stats, full_r0
        artifact.mkdir(parents=True, exist_ok=True); model_path = artifact/"model.pt"; frozen.save(model_path)
        normalization = {"feature_names": feature_names, "mean": mean.tolist(), "std": std.tolist(),
                         "source": "development_train_groups_only", "train_group_count": len(train_groups)}
        write_json(artifact/"normalization.json", normalization)
        feature_schema = {"source_stage3c_schema_hash": stage3c_freeze["feature_schema_hash"],
                          "features": feature_names, "type_agnostic": True}
        write_json(artifact/"feature_schema.json", feature_schema)
        metadata = {"python_version": platform.python_version(), "torch_version": torch.__version__, "seed": raw["seed"],
            "train_groups": len(train_groups), "tune_groups": len(tune_groups), "group_split_hash": split_hash,
            "round0_train": r0_stats, "round1_train": r1_stats, "full_round0": full_r0_stats,
            "full_selected": full_selected_stats, "selected": selected, "model_metadata": frozen.metadata}
        write_json(artifact/"training_metadata.json", metadata); write_json(output/"training_summary.json", metadata)
        write_json(output/"ranking_metrics_development.json", tune_metrics)
        write_json(output/"positive_rank_diagnostics_development.json", tune_ranks)
        norm_path = artifact/"normalization.json"
        freeze = {"status": "FROZEN_AFTER_DEVELOPMENT", "base_stage3c_commit": raw["base_stage3c_commit"],
            "stage3a_proposer_model_hash": stage3c_freeze["stage3a_proposer_model_hash"], "stage3a_pair_budget": 32,
            "candidate_bank_version": BANK_VERSION, "feature_schema_hash": stage3c_freeze["feature_schema_hash"],
            "normalization_stats_hash": sha256(norm_path), "model_hash": sha256(model_path),
            "group_split_hash": split_hash, "relation_prompt_version": stage3a_freeze["relation_prompt_version"],
            "seed": raw["seed"], "selected": selected, "validation_configuration_frozen": True}
        write_json(freeze_path, freeze); write_json(output/"config.json", raw)
        for checkpoint in (checkpoint_model, checkpoint_norm, checkpoint_stats):
            checkpoint.unlink(missing_ok=True)
        print(json.dumps({"selected": selected, "metrics": tune_metrics}, indent=2)); return
    freeze = json.loads(freeze_path.read_text(encoding="utf-8")); model_path = artifact/"model.pt"; norm_path = artifact/"normalization.json"
    verify_freeze(freeze, {"base_stage3c_commit": raw["base_stage3c_commit"],
        "stage3a_proposer_model_hash": stage3c_freeze["stage3a_proposer_model_hash"], "stage3a_pair_budget": 32,
        "candidate_bank_version": BANK_VERSION, "feature_schema_hash": stage3c_freeze["feature_schema_hash"],
        "normalization_stats_hash": norm_path, "model_hash": model_path, "group_split_hash": EXPECTED_SPLIT_HASH,
        "relation_prompt_version": stage3a_freeze["relation_prompt_version"], "seed": raw["seed"]})
    scorer = NonlinearSetRanker.load(model_path, norm_path)
    metrics, ranks, cache = evaluate(queries, gold, retriever, {"frozen_mlp": scorer})
    stage3c_validation = json.loads((ROOT/stage3c["output_dir"]/"ranking_metrics_validation.json").read_text(encoding="utf-8"))
    metrics["stage3a_greedy"] = stage3c_validation["stage3a_greedy"]
    metrics["stage3c_linear_r1"] = stage3c_validation["frozen_pairwise_agnostic"]
    write_json(output/"ranking_metrics_validation.json", metrics)
    write_json(output/"positive_rank_diagnostics_validation.json", ranks)
    write_json(output/"cache_diagnostics_validation.json", cache)
    accepted = metrics["frozen_mlp"]["flow_complete_at_5"] > metrics["stage3a_greedy"]["flow_complete_at_5"]
    summary = {"development_selection": freeze["selected"], "validation_metrics": metrics,
        "positive_rank_diagnostics": ranks, "cache": cache,
        "final_v6_decision": "Stage3D accepted" if accepted else "Stage3A retained",
        "method_development_status": "nonlinear ranking successful" if accepted else "ranking branch stopped",
        "next": "benchmark integrity audit -> first sealed test", "test_gold_accessed": False,
        "sealed_test_evaluator_accessed": False, "private_test_artifact_accessed": False,
        "target_method_test_runs": 0, "new_llm_calls": 0, "new_http_requests": 0}
    write_json(output/"summary.json", summary); print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
