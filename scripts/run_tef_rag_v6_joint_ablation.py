"""Validation-only joint ablation: rule pair prefilter plus frozen greedy set selector."""
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


def run(legacy_cache: Path, allow_api: bool):
    queries = validation_queries()
    client, retriever, stage2a_path, b1_path = runtime(legacy_cache)
    preflight = pair_cache_preflight(queries, retriever, client)
    write_json(OUT / "cache_preflight.json", preflight)
    if preflight["cache_misses"] and not allow_api:
        raise RuntimeError(f"{preflight['cache_misses']} relation judgments are absent from cache; rerun with --allow-api")
    if not allow_api:
        client.transport = lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected relation cache miss"))
    gold = {row["query_id"]: row for row in load_jsonl(PUBLIC / "gold_validation.jsonl")}
    if set(gold) != {q["query_id"] for q in queries}:
        raise RuntimeError("validation query/gold mismatch")
    predictions, scored, diagnostics = [], [], Counter()
    bank_sizes = []
    for index, query in enumerate(queries, 1):
        public, prediction, _, _, bank = context(query, retriever, prefilter_mode="improved",
                                                  require_cache=not allow_api)
        if retriever.relation_scorer.pair_proposer is not None:
            raise RuntimeError("learned pair proposer was enabled")
        rd = prediction["relation_diagnostics"]
        if rd["client_failure_pair_count"]:
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
        scored.append(evaluate_prediction(prediction, gold[query["query_id"]], 5))
        bank_sizes.append(len(bank))
        diagnostics.update(cache_lookups=rd["cache_lookup_count"], cache_hits=rd["cache_hit_count"],
                           llm_pairs=rd["llm_called_pair_count"], requests=rd["request_count"],
                           retries=rd["retry_count"], pair_count=rd["prefiltered_pair_count"])
        if index % 40 == 0:
            print(f"joint ablation: {index}/480", flush=True)
    metrics = average(scored)
    write_json(OUT / "validation_predictions.json", predictions)
    write_json(OUT / "validation_metrics.json", metrics)
    manifest = {
        "name": NAME, "base_release_commit": "7521229b20e0fa70d4cb42b16f32ebea01778364",
        "split": "validation", "query_count": 480, "test_split_run": False,
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
        "validation_queries_sha256": sha256(PUBLIC / "queries_validation.jsonl"),
        "validation_gold_sha256": sha256(PUBLIC / "gold_validation.jsonl"),
        "legacy_cache_checked": legacy_cache.exists(), "cache_hits_before_run":
            preflight["lookups"] - preflight["cache_misses"], "cache_preflight": preflight,
        "runtime_diagnostics": dict(diagnostics), "candidate_bank_total": sum(bank_sizes),
        "prediction_sha256": sha256(OUT / "validation_predictions.json"),
    }
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"metrics": metrics, "diagnostics": dict(diagnostics)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "run"))
    parser.add_argument("--reuse-cache", type=Path, default=LEGACY_CACHE)
    parser.add_argument("--allow-api", action="store_true")
    args = parser.parse_args()
    queries = validation_queries()
    if args.action == "preflight":
        client, retriever, _, _ = runtime(args.reuse_cache)
        print(json.dumps(pair_cache_preflight(queries, retriever, client), indent=2))
    else:
        run(args.reuse_cache, args.allow_api)


if __name__ == "__main__":
    main()
