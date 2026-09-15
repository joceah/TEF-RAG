"""Validate public and locally sealed TEF-RAG v6 benchmark v1 artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.generate_tef_v6_benchmark_v1 import CONFIG, DEFAULT_OUTPUT, DEFAULT_SEALED, PROTOCOL, SPLITS, latest_metrics


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_dataset(output=DEFAULT_OUTPUT, sealed=DEFAULT_SEALED, write_summary=True):
    output, sealed = Path(output), Path(sealed)
    config, protocol = read(CONFIG), read(PROTOCOL)
    public = output / "public"
    evidence = lines(public / "evidence.jsonl")
    queries = sum((lines(public / f"queries_{split}.jsonl") for split in SPLITS), [])
    chains = sum((lines(public / f"chains_{split}.jsonl") for split in SPLITS), [])
    gold_public = lines(public / "gold_development.jsonl") + lines(public / "gold_validation.jsonl")
    gold_test = lines(sealed)
    errors = []
    check = lambda condition, message: errors.append(message) if not condition else None
    check(len(chains) == 400, "chain count")
    check(len({q["intent_id"] for q in queries}) == 1200, "intent count")
    check(len(queries) == 2400, "query count")
    check(len({c["asset_id"] for c in chains}) == 100, "asset count")
    for layer in ("realistic", "challenge"):
        check(sum(c["layer"] == layer for c in chains) == 200, f"{layer} chain count")
        for split, expected in (("development", 120), ("validation", 40), ("test", 40)):
            check(sum(c["layer"] == layer and c["split"] == split for c in chains) == expected, f"{layer}/{split} count")
    chain_ids, query_ids, evidence_ids = [set(row[key] for row in rows) for rows, key in ((chains, "chain_id"), (queries, "query_id"), (evidence, "evidence_id"))]
    check(len(chain_ids) == len(chains), "chain IDs unique")
    check(len(query_ids) == len(queries), "query IDs unique")
    check(len(evidence_ids) == len(evidence), "evidence IDs unique")
    check(all(q["chain_id"] in chain_ids for q in queries), "query chain references")
    check(all(e["chain_id"] in chain_ids for e in evidence), "evidence chain references")
    check(all(e["event_time"] <= next(q["query_time"] for q in queries if q["chain_id"] == e["chain_id"]) for e in evidence), "event/query time order")
    for family_field in ("scenario_family_id", "template_family_id"):
        split_by_family = defaultdict(set)
        for chain in chains:
            split_by_family[chain[family_field]].add(chain["split"])
        check(all(len(values) == 1 for values in split_by_family.values()), f"{family_field} isolation")
    challenge_assets = {split: {c["asset_id"] for c in chains if c["layer"] == "challenge" and c["split"] == split} for split in SPLITS}
    check(not challenge_assets["development"] & challenge_assets["validation"] and not challenge_assets["development"] & challenge_assets["test"] and not challenge_assets["validation"] & challenge_assets["test"], "challenge asset isolation")
    realistic_assets = {c["asset_id"] for c in chains if c["layer"] == "realistic"}
    check(not realistic_assets & set.union(*challenge_assets.values()), "layer asset isolation")
    expected_difficulties = set(config["challenge_composition"]["difficulties"])
    counts = Counter(c["primary_difficulty"] for c in chains if c["primary_difficulty"])
    check(set(counts) == expected_difficulties and all(counts[d] == 20 for d in expected_difficulties), "primary difficulty counts")
    check(sum(c["mixture_category"] == "compositional_hard" and c["layer"] == "challenge" for c in chains) == 40, "compositional count")
    gold = gold_public + gold_test
    check(len(gold) == 2400 and len({g["query_id"] for g in gold}) == 2400, "gold coverage")
    for row in gold:
        for group in row["required_groups"]:
            check(set(group["acceptable_evidence_ids"]) <= evidence_ids, "group evidence reference")
        groups = {group["group_id"]: set(group["acceptable_evidence_ids"]) for group in row["required_groups"]}
        for edge in row["required_flow_edges"]:
            check(edge["from_group"] in groups and edge["to_group"] in groups, "flow group reference")
            check(all(pair[0] in groups[edge["from_group"]] and pair[1] in groups[edge["to_group"]] for pair in edge["allowed_endpoint_pairs"]), "allowed endpoint pair")
    forbidden = {"required_groups", "required_flow_edges", "canonical_task_support_flow", "acceptable_evidence_ids", "reference_evidence_ids", "answer", "gold"}
    check(all(not forbidden.intersection(row) for row in queries + evidence), "gold leakage into public inputs")
    check(not (public / "gold_test.jsonl").exists(), "test gold public")
    check(all(g["query_id"] in {q["query_id"] for q in queries if q["split"] != "test"} for g in gold_public), "public gold split")
    for row in evidence:
        telemetry = row["telemetry"]
        check(telemetry["current_derivation"] == "I=P/V", "current derivation")
        check(abs(telemetry["current_a"] - telemetry["power_w"] / telemetry["voltage_v"]) < 0.001, "current consistency")
        check("ambient_temperature_c" in telemetry and "cell_temperature_c" in telemetry, "ambient/cell separation")
        check(0 <= telemetry["normalized_p_rate"] <= 1.0, "normalized P-rate")
    check(sum(c["gross_anomaly_segment"] for c in chains) / len(chains) <= config["telemetry"]["gross_anomaly_chain_cap"], "gross anomaly chain cap")
    check(protocol["status"] == "FROZEN_BEFORE_DATA_GENERATION", "protocol status")
    gates = latest_metrics(evidence, queries, gold, config["gates"]["top_k"])
    check(gates["recency_solvable_at_5_rate"] <= 0.4, "structural gate")
    check(gates["latest5_complete_at_5_rate"] <= 0.4, "Latest-5 gate")
    check(all(row["query_rows"] == 120 and row["recency_solvable_at_5_rate"] <= 0.5 for row in gates["major_strata"].values()), "major stratum gate")
    manifest = read(output / "manifest.json")
    check(manifest["sealed_test_artifact"]["sha256"] == sha(sealed), "sealed hash")
    check(manifest["sealed_test_artifact"]["record_count"] == 480, "sealed record count")
    check(all(sha(output / relative) == expected for relative, expected in manifest["public_artifact_hashes"].items()), "public hashes")
    summary = {"status": "PASSED" if not errors else "FAILED", "errors": errors, "counts": {"chains": len(chains), "intents": len({q["intent_id"] for q in queries}), "queries": len(queries), "assets": len({c["asset_id"] for c in chains})}, "gates": gates, "sealed_artifact_sha256_verified": not errors or manifest["sealed_test_artifact"]["sha256"] == sha(sealed)}
    if write_summary:
        path = output / "validation_summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return errors, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED)
    args = parser.parse_args()
    errors, summary = validate_dataset(args.output, args.sealed)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
