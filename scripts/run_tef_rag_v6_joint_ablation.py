"""Joint ablation: rule pair prefilter plus frozen greedy set selector."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_tef_rag_v6_stage3b import context
from tef_rag_v6 import LLMRelationClient, LLMRelationConfig, QueryConditionedRelationScorer, TEFRAGV6, V6Config, load_jsonl
from tef_rag_v6.evaluation import average, evaluate_prediction

NAME = "w/o Pair Proposal + Nonlinear Ranker"
PUBLIC = ROOT / "data/retrieval/tef_v6_temporal_hard_benchmark_v1/public"
OUT = ROOT / "results/v6/ablation_no_pair_no_ranknet"
LEGACY_CACHE = ROOT.parent / ".github_export/TEF-RAG/.cache/tef_rag_v6_llm_relation"
TEST_CACHE = ROOT.parent / ".github_export/TEF-RAG/.cache/tef_rag_v6_test_relation"
TEST_EVALUATOR_SHA256 = "477bb709f3dfdb672ce5a7f5c93168e0791c7a90cb247c62a6072bd8dee7c9f3"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_env():
    path = ROOT.parent / "local.env"
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    for key in ("API_KEY", "ENDPOINT"):
        if not values.get(key):
            raise RuntimeError(f"local.env missing {key}")
    return values


def install_read_through_cache(client: LLMRelationClient, legacy: Path):
    local_load = client._load_cache

    def load(fingerprint: str):
        cached = local_load(fingerprint)
        if cached is not None:
            return cached
        path = legacy / fingerprint[:2] / f"{fingerprint}.json"
        if not path.exists():
            return None
        try:
            value = read_json(path)
            if value.get("fingerprint") == fingerprint:
                judgment = value["judgment"]
                if judgment.get("reason_code") != "client_failure_after_retries":
                    return judgment
        except (OSError, KeyError, ValueError):
            return None
        return None

    client._load_cache = load


def runtime(legacy_cache: Path):
    stage2a_path = ROOT / "configs/tef_rag_v6_stage2a_llm_relation.json"
    b1_path = ROOT / "configs/tef_rag_v6_stage2b1_correction.json"
    stage2a, b1 = read_json(stage2a_path), read_json(b1_path)
    base = V6Config.from_dict(read_json(ROOT / stage2a["pipeline_config"]))
    config = replace(base, search_pool_k=b1["search_pool_k"], **b1["beam"])
    env = local_env()
    relation = dict(stage2a["relation"])
    # The frozen relation stage uses deepseek-chat from its config.  local.env
    # supplies credentials/endpoint; its MODEL may target the generation stage.
    relation.update(endpoint=env["ENDPOINT"], cache_dir=str(OUT / "api_cache"))
    # Stage3A originally warmed relation judgments through the compact
    # single-case protocol in batches of at most eight pairs. Reuse that
    # protocol when this checkout has cache misses.
    relation_config = replace(LLMRelationConfig.from_dict(relation),
                              case_batch_mode=True, batch_size=8, cases_per_request=1)
    taxonomy = read_json(ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/metadata/relation_taxonomy.json")["relation_types"]
    client = LLMRelationClient(relation_config, taxonomy, api_key=env["API_KEY"])
    install_read_through_cache(client, legacy_cache)
    scorer = QueryConditionedRelationScorer(client, config.relation_threshold,
                                            pair_proposer=None, pair_budget=32)
    retriever = TEFRAGV6(load_jsonl(PUBLIC / "evidence.jsonl"), config,
                         relation_scorer=scorer)
    return client, retriever, stage2a_path, b1_path


def validation_queries():
    queries = load_jsonl(PUBLIC / "queries_validation.jsonl")
    if len(queries) != 480 or len({q["query_id"] for q in queries}) != 480:
        raise RuntimeError("validation must have exactly 480 unique queries")
    return queries


def split_queries(split: str):
    if split == "validation":
        return validation_queries()
    queries = load_jsonl(PUBLIC / "queries_test.jsonl")
    if len(queries) != 480 or len({q["query_id"] for q in queries}) != 480:
        raise RuntimeError("test must have exactly 480 unique queries")
    return queries


def pair_cache_preflight(queries, retriever, client):
    missing = lookups = 0
    for query in queries:
        public = retriever._public_query(query)
        eligible = [item for item in retriever.candidate_retrieval(public)
                    if retriever.temporal_eligibility(item["document"], public)[0]]
        if not eligible:
            continue
        scores = retriever._node_scores(public, eligible)
        pool = sorted(eligible, key=lambda item: (-scores[item["document"]["evidence_id"]]["total"],
                                                   item["document"]["evidence_id"]))[:retriever.config.search_pool_k]
        pairs, _ = retriever.relation_scorer.prefilter(pool, scores, retriever._relation_kind,
                                                       retriever._similarity, "improved", query=public)
        for pair in pairs:
            lookups += 1
            fingerprint = client.fingerprint(public, pair["source"], pair["target"])
            missing += client._load_cache(fingerprint) is None
    return {"lookups": lookups, "cache_misses": missing}


def run(legacy_cache: Path, allow_api: bool, split: str = "validation"):
    queries = split_queries(split)
    prediction_path = OUT / f"{split}_predictions.json"
    if split == "test" and prediction_path.exists():
        raise RuntimeError("test predictions already exist; refusing to overwrite frozen output")
    client, retriever, stage2a_path, b1_path = runtime(legacy_cache)
    preflight = pair_cache_preflight(queries, retriever, client)
    write_json(OUT / ("cache_preflight.json" if split == "validation" else "test_cache_preflight.json"), preflight)
    if preflight["cache_misses"] and not allow_api:
        raise RuntimeError(f"{preflight['cache_misses']} relation judgments are absent from cache; rerun with --allow-api")
    if not allow_api:
        client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected relation cache miss"))
    # Test predictions are frozen before the test evaluator is read.
    gold = {row["query_id"]: row for row in load_jsonl(PUBLIC / "gold_validation.jsonl")} if split == "validation" else None
    if gold is not None and set(gold) != {q["query_id"] for q in queries}:
        raise RuntimeError("validation query/gold mismatch")
    predictions, scored, diagnostics, bank_sizes = [], [], Counter(), []
    progress_path = OUT / "test_progress.json"
    if split == "test" and progress_path.exists():
        progress = read_json(progress_path)
        predictions = progress["predictions"]
        bank_sizes = progress["bank_sizes"]
        diagnostics = Counter(progress["diagnostics"])
        if (len(predictions) != len(bank_sizes) or
                [row["query_id"] for row in predictions] != [q["query_id"] for q in queries[:len(predictions)]]):
            raise RuntimeError("test progress query order mismatch")

    def save_progress():
        if split == "test":
            write_json(progress_path, {"predictions": predictions, "bank_sizes": bank_sizes,
                                       "diagnostics": dict(diagnostics)})

    for index in range(len(predictions), len(queries)):
        query = queries[index]
        public, prediction, _, _, bank = context(query, retriever, prefilter_mode="improved",
                                                  require_cache=not allow_api)
        if retriever.relation_scorer.pair_proposer is not None:
            raise RuntimeError("learned pair proposer was enabled")
        rd = prediction["relation_diagnostics"]
        if rd["client_failure_pair_count"]:
            save_progress()
            raise RuntimeError(f"relation judging failed for {query['query_id']}")
        if rd["prefilter_mode"] != "improved" or prediction["search_diagnostics"]["mode"] != "greedy":
            raise RuntimeError("joint ablation mode mismatch")
        ids = prediction["selected_evidence_ids"]
        if len(ids) > 5 or len(ids) != len(set(ids)):
            raise RuntimeError(f"invalid Top-5 result for {query['query_id']}")
        if any(not retriever.temporal_eligibility(retriever.by_id[eid], public)[0] for eid in ids):
            raise RuntimeError(f"future or unavailable evidence for {query['query_id']}")
        if any(retriever.by_id[eid]["asset_id"] != public["asset_id"] for eid in ids):
            raise RuntimeError(f"wrong asset evidence for {query['query_id']}")
        predictions.append({"query_id": query["query_id"], "selected_evidence_ids": ids,
                            "relations": prediction["relations"], "uncertainty": prediction["uncertainty"],
                            "relation_graph": prediction["relation_graph"],
                            "relation_diagnostics": rd, "search_diagnostics": prediction["search_diagnostics"],
                            "candidate_bank_size": len(bank)})
        if gold is not None:
            scored.append(evaluate_prediction(prediction, gold[query["query_id"]], 5))
        bank_sizes.append(len(bank))
        diagnostics.update(cache_lookups=rd["cache_lookup_count"], cache_hits=rd["cache_hit_count"],
                           llm_pairs=rd["llm_called_pair_count"], requests=rd["request_count"],
                           retries=rd["retry_count"], pair_count=rd["prefiltered_pair_count"])
        if (index + 1) % 40 == 0:
            save_progress()
            print(f"joint ablation {split}: {index + 1}/480", flush=True)
    save_progress()
    write_json(prediction_path, predictions)
    metrics = average(scored) if gold is not None else None
    if metrics is not None:
        write_json(OUT / "validation_metrics.json", metrics)
    manifest = {
        "name": NAME, "base_release_commit": "7521229b20e0fa70d4cb42b16f32ebea01778364",
        "split": split, "query_count": 480, "test_split_run": split == "test",
        "pair_selection": "existing improved rule prefilter", "pair_proposer_loaded": False,
        "set_selection": "existing greedy evidence-set selector", "nonlinear_ranknet_loaded": False,
        "candidate_set_construction": "existing stage3b.context/candidate_bank",
        "search_pool_k": retriever.config.search_pool_k, "final_k": retriever.config.final_k,
        "configured_pair_budget": retriever.relation_scorer.pair_budget,
        "improved_prefilter_effective_limit": max(24, client.config.max_pairs_per_query),
        "relation_prompt_version": client.config.prompt_version,
        "relation_confidence_threshold": client.config.llm_confidence_threshold,
        "relation_model": client.config.model, "relation_temperature": client.config.temperature,
        "stage2a_config_sha256": sha256(stage2a_path), "stage2b1_config_sha256": sha256(b1_path),
        "evidence_sha256": sha256(PUBLIC / "evidence.jsonl"),
        f"{split}_queries_sha256": sha256(PUBLIC / f"queries_{split}.jsonl"),
        "legacy_cache_checked": legacy_cache.exists(), "cache_hits_before_run":
            preflight["lookups"] - preflight["cache_misses"], "cache_preflight": preflight,
        "runtime_diagnostics": dict(diagnostics), "candidate_bank_total": sum(bank_sizes),
        "prediction_sha256": sha256(prediction_path),
    }
    if split == "validation":
        manifest["validation_gold_sha256"] = sha256(PUBLIC / "gold_validation.jsonl")
    else:
        manifest["test_evaluator_accessed_before_prediction_freeze"] = False
    write_json(OUT / ("manifest.json" if split == "validation" else "test_manifest.json"), manifest)
    print(json.dumps({"metrics": metrics, "diagnostics": dict(diagnostics)}, indent=2))


def evaluate_test():
    prediction_path = OUT / "test_predictions.json"
    manifest_path = OUT / "test_manifest.json"
    manifest = read_json(manifest_path)
    if sha256(prediction_path) != manifest["prediction_sha256"]:
        raise RuntimeError("test predictions changed after freeze")
    evaluator_path = PUBLIC / "test_evaluator.jsonl"
    if sha256(evaluator_path) != TEST_EVALUATOR_SHA256:
        raise RuntimeError("test evaluator SHA mismatch")
    queries = split_queries("test")
    predictions = read_json(prediction_path)
    if len(predictions) != 480 or [p["query_id"] for p in predictions] != [q["query_id"] for q in queries]:
        raise RuntimeError("test prediction query count/order mismatch")
    sealed = load_jsonl(evaluator_path)
    gold = {row["query"]["query_id"]: row["gold"] for row in sealed}
    if len(gold) != 480 or set(gold) != {q["query_id"] for q in queries}:
        raise RuntimeError("test evaluator query mismatch")
    metrics = average([evaluate_prediction(row, gold[row["query_id"]], 5) for row in predictions])
    write_json(OUT / "test_metrics.json", metrics)
    manifest["test_evaluator_sha256"] = TEST_EVALUATOR_SHA256
    manifest["test_evaluator_accessed_after_prediction_freeze"] = True
    manifest["test_metrics_sha256"] = sha256(OUT / "test_metrics.json")
    write_json(manifest_path, manifest)
    print(json.dumps(metrics, indent=2))


def verify_test():
    manifest = read_json(OUT / "test_manifest.json")
    predictions = read_json(OUT / "test_predictions.json")
    queries = split_queries("test")
    if sha256(OUT / "test_predictions.json") != manifest["prediction_sha256"]:
        raise RuntimeError("test prediction hash mismatch")
    if len(predictions) != 480 or [p["query_id"] for p in predictions] != [q["query_id"] for q in queries]:
        raise RuntimeError("test prediction count/order mismatch")
    client, retriever, _, _ = runtime(TEST_CACHE)
    client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("verification must be cache-only"))
    if retriever.relation_scorer.pair_proposer is not None:
        raise RuntimeError("learned pair proposer was loaded")
    for query, saved in zip(queries, predictions):
        public, repeated, _, _, bank = context(query, retriever, prefilter_mode="improved", require_cache=True)
        ids = saved["selected_evidence_ids"]
        if (ids != repeated["selected_evidence_ids"] or
                saved["relation_diagnostics"]["prefilter_pairs"] != repeated["relation_diagnostics"]["prefilter_pairs"] or
                saved["candidate_bank_size"] != len(bank)):
            raise RuntimeError(f"test fallback/greedy reproduction mismatch: {query['query_id']}")
        if (len(ids) > 5 or len(ids) != len(set(ids)) or
                any(not retriever.temporal_eligibility(retriever.by_id[eid], public)[0] or
                    retriever.by_id[eid]["asset_id"] != public["asset_id"] for eid in ids)):
            raise RuntimeError(f"invalid test evidence: {query['query_id']}")
        rd = repeated["relation_diagnostics"]
        if (rd["prefilter_mode"] != "improved" or rd["client_failure_pair_count"] or
                rd["request_count"] or rd["cache_hit_count"] != rd["cache_lookup_count"] or
                repeated["search_diagnostics"]["mode"] != "greedy"):
            raise RuntimeError(f"test protocol mismatch: {query['query_id']}")
    print("verified 480 test predictions, temporal/asset eligibility, rule pair fallback, greedy selection, and cache-only reproduction")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "run", "evaluate-test", "verify-test"))
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--reuse-cache", type=Path)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    if args.action == "evaluate-test":
        evaluate_test()
        return
    if args.action == "verify-test":
        verify_test()
        return
    queries = split_queries(args.split)
    legacy_cache = args.reuse_cache or (TEST_CACHE if args.split == "test" else LEGACY_CACHE)
    if args.action == "preflight":
        client, retriever, _, _ = runtime(legacy_cache)
        print(json.dumps(pair_cache_preflight(queries, retriever, client), indent=2))
    else:
        run(legacy_cache, args.allow_api, args.split)


if __name__ == "__main__":
    main()
