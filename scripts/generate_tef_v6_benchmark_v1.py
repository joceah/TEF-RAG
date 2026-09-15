"""Deterministically generate the frozen TEF-RAG v6 benchmark candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/tef_v6_benchmark_generation_v1.json"
PROTOCOL = ROOT / "configs/temporal_hard_benchmark_protocol_v1.json"
DEFAULT_OUTPUT = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1"
DEFAULT_SEALED = ROOT / ".local_sealed/tef_v6_benchmark_v1_test_evaluator.jsonl"
SPLITS = ("development", "validation", "test")
LAYERS = ("realistic", "challenge")
EVENT_TYPES = (
    "state_observation", "alarm", "diagnosis", "work_order", "inspection",
    "correction", "reopen", "supersession", "procedure_applicability",
    "repair", "verification", "uncertainty", "prediction_trend",
)
INTENTS = ("identify_cause", "select_action", "reconstruct_flow")
SPLIT_TERMS = {
    "development": ("请判断", "综合当前记录说明"),
    "validation": ("截至该时点应如何研判", "依据可用证据给出结论"),
    "test": ("在信息截止时刻需要确认什么", "请还原当时可成立的判断"),
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dump_lines(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso(dt: datetime):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def allocate_assets(layer: str, split: str, index: int):
    if layer == "realistic":
        return f"R-ASSET-{index % 50 + 1:03d}"
    offsets = {"development": 0, "validation": 30, "test": 40}
    sizes = {"development": 30, "validation": 10, "test": 10}
    return f"C-ASSET-{offsets[split] + index % sizes[split] + 1:03d}"


def chain_specs(config):
    specs = []
    mixtures = config["realistic_mixture"]
    for split in SPLITS:
        local = 0
        for category, counts in mixtures.items():
            for _ in range(counts[split]):
                specs.append(("realistic", split, category, [], None, local))
                local += 1
    difficulties = config["challenge_composition"]["difficulties"]
    per = config["challenge_composition"]["single_primary_per_difficulty"]
    for split in SPLITS:
        local = 0
        for difficulty in difficulties:
            for _ in range(per[split]):
                specs.append(("challenge", split, "single_primary_hard", [difficulty], difficulty, local))
                local += 1
        count = config["challenge_composition"]["compositional"][split]
        for i in range(count):
            labels = [difficulties[(i + local) % 8], difficulties[(i + local + 3) % 8]]
            if i % 3 == 0:
                labels.append(difficulties[(i + local + 5) % 8])
            specs.append(("challenge", split, "compositional_hard", labels, None, local))
            local += 1
    return specs


def required_positions(layer: str, category: str):
    if layer == "challenge":
        return (0, 1, 2)
    if category == "routine_or_mostly_recency_solvable":
        return (6, 7, 8)
    if category == "single_temporal_complication":
        return (2, 6, 8)
    return (1, 3, 7)


def make_gold(query_id, chain_id, required_ids, intent_index):
    selections = ((0, 1), (1, 2), (0, 1, 2))[intent_index]
    groups = []
    for group_number, evidence_position in enumerate(selections, 1):
        groups.append({"group_id": f"G{group_number}", "acceptable_evidence_ids": [required_ids[evidence_position]]})
    edges = []
    for edge_index in range(len(groups) - 1):
        edges.append({
            "edge_id": f"FLOW-{edge_index + 1}",
            "from_group": groups[edge_index]["group_id"],
            "to_group": groups[edge_index + 1]["group_id"],
            "relation_type": "supports",
            "allowed_endpoint_pairs": [[groups[edge_index]["acceptable_evidence_ids"][0], groups[edge_index + 1]["acceptable_evidence_ids"][0]]],
        })
    return {
        "query_id": query_id,
        "chain_id": chain_id,
        "required_groups": groups,
        "required_flow_edges": edges,
        "reference_evidence_ids": [required_ids[i] for i in selections],
        "canonical_task_support_flow": {"required_groups": groups, "required_flow_edges": edges},
        "review_status": "PENDING_AI_SEMANTIC_REVIEW",
    }


def query_text(asset, intent, split, phrasing, labels):
    lead = SPLIT_TERMS[split][phrasing]
    focus = {
        "identify_cause": "异常的有效诊断依据与原因",
        "select_action": "适用的处置动作及其前置依据",
        "reconstruct_flow": "从现象到诊断再到处置的证据流",
    }[intent]
    context = "、".join(labels[:2]) if labels else "当前运行事件"
    endings = ("。", "，并排除已失效或尚不可见的记录。")
    return f"{lead}{asset}在{context}下{focus}{endings[phrasing]}"


def generate(config, seed):
    rng = random.Random(seed)
    chains, evidence, queries, gold_public, gold_test = [], [], [], [], []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for global_index, (layer, split, category, labels, primary, local_index) in enumerate(chain_specs(config)):
        chain_id = f"{layer[0].upper()}-{split[0].upper()}-CHAIN-{local_index + 1:03d}"
        asset_id = allocate_assets(layer, split, local_index)
        family_key = primary or category
        scenario_family_id = f"SF-{layer}-{split}-{family_key}-{local_index % 5:02d}"
        template_family_id = f"TF-{layer}-{split}-{family_key}-{local_index % 7:02d}"
        start = base + timedelta(days=global_index * 2 + {"development": 0, "validation": 500, "test": 1000}[split])
        req_positions = required_positions(layer, category)
        required_ids = [f"{chain_id}-EV-{position + 1:02d}" for position in req_positions]
        telemetry_seed = seed * 1000 + global_index
        chain = {
            "chain_id": chain_id, "layer": layer, "split": split, "asset_id": asset_id,
            "scenario_family_id": scenario_family_id, "template_family_id": template_family_id,
            "difficulty_labels": labels, "primary_difficulty": primary, "mixture_category": category,
            "telemetry_seed": telemetry_seed, "conceptual_raw_cadence_seconds": 1,
            "rag_evidence_cadence_seconds": 60, "gross_anomaly_segment": global_index < 8,
            "review_status": "PENDING_AI_SEMANTIC_REVIEW",
            "structural_features": {
                "multiple_episodes": "MULTI_EPISODE_DISAMBIGUATION" in labels or "SIMILAR_SYMPTOM_DIFFERENT_CAUSE" in labels,
                "paired_query_cutoffs": any(label in labels for label in ("CUTOFF_SENSITIVE", "LATE_ARRIVING_EVIDENCE")),
                "late_arrival": "LATE_ARRIVING_EVIDENCE" in labels,
                "supersession": "SUPERSEDED_DIAGNOSIS" in labels,
                "procedure_versions": "PROCEDURE_VERSIONING" in labels,
                "cross_source": "CROSS_SOURCE_REQUIRED" in labels,
                "persistent_uncertainty": "PERSISTENT_UNCERTAINTY" in labels,
            },
        }
        chains.append(chain)
        for position in range(9):
            event_time = start + timedelta(hours=position)
            source_type = EVENT_TYPES[(global_index + position) % len(EVENT_TYPES)]
            if "PERSISTENT_UNCERTAINTY" in labels and position == 8:
                source_type = "uncertainty"
            elif "PROCEDURE_VERSIONING" in labels and position < 3:
                source_type = "procedure_applicability"
            elif "CROSS_SOURCE_REQUIRED" in labels and position < 3:
                source_type = ("state_observation", "diagnosis", "work_order")[position]
            elif "PERSISTENT_UNCERTAINTY" in labels and position == 2:
                source_type = "uncertainty"
            elif "SUPERSEDED_DIAGNOSIS" in labels and position in (1, 2):
                source_type = ("diagnosis", "supersession")[position - 1]
            if "LATE_ARRIVING_EVIDENCE" in labels and position == req_positions[1]:
                available_at = event_time + timedelta(hours=3)
            else:
                available_at = event_time + timedelta(minutes=(position % 3) * 5)
            rate = round(0.3 + 0.1 * ((position + global_index) % 7), 2)
            voltage = round(3.0 + 0.03 * ((position + global_index) % 10), 3)
            power_w = round(rate * 280 * 3.2, 3)
            current_a = round(power_w / voltage, 3)
            cell_temp = round(22 + ((position * 3 + global_index) % 31), 1)
            ambient_temp = round(10 + ((position + global_index) % 31), 1)
            row = {
                "evidence_id": f"{chain_id}-EV-{position + 1:02d}", "chain_id": chain_id,
                "layer": layer, "split": split, "asset_id": asset_id, "source_type": source_type,
                "event_time": iso(event_time), "available_at": iso(available_at),
                "text": f"{asset_id} {source_type} 记录：episode {global_index + 1}，阶段 {position + 1}，证据按当时可用信息形成。",
                "episode_id": f"{chain_id}-EP-{1 if position < 3 else 2}",
                "telemetry": {"voltage_v": voltage, "ambient_temperature_c": ambient_temp, "cell_temperature_c": cell_temp,
                              "normalized_p_rate": rate, "power_w": power_w, "current_a": current_a,
                              "current_derivation": "I=P/V", "soc_percent": 15 + (position * 7 + global_index) % 76},
                "source_basis_ids": ["HITHIUM_V1_1", "HITHIUM_V3_3"] if source_type in {"state_observation", "prediction_trend"} else [],
                "modeling_choice_ids": ["CELL_TEMPERATURE_BANDS", "NORMALIZED_P_RATE"],
            }
            if source_type == "procedure_applicability":
                version_number = position % 3 + 1
                row.update({"procedure_version": f"V{version_number}", "valid_from": iso(start - timedelta(days=90 - version_number * 10)),
                            "valid_to": iso(start + timedelta(days=30 + version_number * 10)), "supersedes": None if version_number == 1 else f"V{version_number - 1}",
                            "withdrawn_at": None, "model_scope": "280Ah-class-prismatic-LFP",
                            "procedure_step_signature": f"isolate-check-verify-v{version_number}"})
            if "SUPERSEDED_DIAGNOSIS" in labels and position == 2:
                row["supersedes_evidence_id"] = f"{chain_id}-EV-02"
            if "SIMILAR_SYMPTOM_DIFFERENT_CAUSE" in labels:
                row["symptom_signature"] = "temperature_excursion"
                row["authored_cause_code"] = "fan_degradation" if position < 3 else "sensor_drift"
            evidence.append(row)
        for intent_index, intent in enumerate(INTENTS):
            intent_id = f"{chain_id}-INT-{intent_index + 1}"
            for phrasing in range(2):
                query_id = f"{intent_id}-Q{phrasing + 1}"
                if any(label in labels for label in ("CUTOFF_SENSITIVE", "LATE_ARRIVING_EVIDENCE")):
                    query_time = start + timedelta(hours=(3, 8, 12)[intent_index])
                else:
                    query_time = start + timedelta(hours=12)
                query = {
                    "query_id": query_id, "chain_id": chain_id, "intent_id": intent_id,
                    "phrasing_id": f"P{phrasing + 1}", "layer": layer, "split": split,
                    "asset_id": asset_id, "query_time": iso(query_time),
                    "query_text": query_text(asset_id, intent, split, phrasing, labels),
                    "difficulty_labels": labels, "primary_difficulty": primary,
                }
                queries.append(query)
                gold_ids = required_ids
                if "LATE_ARRIVING_EVIDENCE" in labels and intent_index == 0:
                    gold_ids = [f"{chain_id}-EV-01", f"{chain_id}-EV-03", f"{chain_id}-EV-04"]
                gold = make_gold(query_id, chain_id, gold_ids, intent_index)
                (gold_test if split == "test" else gold_public).append(gold)
    rng.shuffle([])  # Pin use of the preregistered RNG without changing stable ordering.
    return chains, evidence, queries, gold_public, gold_test


def latest_metrics(evidence, queries, all_gold, top_k=5):
    by_chain = defaultdict(list)
    for row in evidence:
        by_chain[row["chain_id"]].append(row)
    gold_map = {row["query_id"]: row for row in all_gold}
    outcomes = []
    for query in queries:
        visible = [row for row in by_chain[query["chain_id"]] if row["event_time"] <= query["query_time"] and row["available_at"] <= query["query_time"]]
        selected = {row["evidence_id"] for row in sorted(visible, key=lambda row: (row["event_time"], row["available_at"], row["evidence_id"]), reverse=True)[:top_k]}
        groups = gold_map[query["query_id"]]["required_groups"]
        complete = all(selected.intersection(group["acceptable_evidence_ids"]) for group in groups)
        outcomes.append((query, complete))
    challenge = [value for query, value in outcomes if query["layer"] == "challenge"]
    by_primary = {}
    for difficulty in load(CONFIG)["challenge_composition"]["difficulties"]:
        subset = [value for query, value in outcomes if query["layer"] == "challenge" and query["primary_difficulty"] == difficulty]
        by_primary[difficulty] = {"query_rows": len(subset), "recency_solvable_at_5_rate": sum(subset) / len(subset)}
    rate = sum(challenge) / len(challenge)
    return {"challenge_query_rows": len(challenge), "recency_solvable_at_5_rate": rate, "latest5_complete_at_5_rate": rate, "major_strata": by_primary}


def write_dataset(output: Path, sealed_path: Path, config, seed, attempt):
    if output.exists():
        shutil.rmtree(output)
    chains, evidence, queries, gold_public, gold_test = generate(config, seed)
    public = output / "public"
    dump_lines(public / "evidence.jsonl", evidence)
    for split in SPLITS:
        dump_lines(public / f"queries_{split}.jsonl", [row for row in queries if row["split"] == split])
        dump_lines(public / f"chains_{split}.jsonl", [row for row in chains if row["split"] == split])
    dump_lines(public / "gold_development.jsonl", [row for row in gold_public if "-D-" in row["chain_id"]])
    dump_lines(public / "gold_validation.jsonl", [row for row in gold_public if "-V-" in row["chain_id"]])
    dump_lines(sealed_path, gold_test)
    shutil.copy2(CONFIG, output / "generation_config.json")
    protocol = load(PROTOCOL)
    dump(output / "source_registry.json", protocol["public_sources"])
    assets = sorted({row["asset_id"] for row in chains})
    split_counts = {layer: {split: sum(row["layer"] == layer and row["split"] == split for row in chains) for split in SPLITS} for layer in LAYERS}
    difficulty_counts = Counter(row["primary_difficulty"] for row in chains if row["primary_difficulty"])
    gates = latest_metrics(evidence, queries, gold_public + gold_test)
    generation_summary = {
        "dataset_status": config["dataset_status"], "review_status": config["review_status"],
        "accepted_seed": seed, "generation_attempt": attempt,
        "counts": {"chains": len(chains), "primary_intents": len({row["intent_id"] for row in queries}), "query_rows": len(queries), "assets": len(assets)},
        "split_chain_counts": split_counts, "primary_difficulty_chain_counts": dict(sorted(difficulty_counts.items())),
        "test_gold_public": False, "target_method_runs": 0, "semantic_review_performed": False,
    }
    dump(output / "generation_summary.json", generation_summary)
    dump(output / "gate_summary.json", gates)
    dump(output / "validation_summary.json", {"status": "PENDING_DETERMINISTIC_VALIDATION"})
    (output / "README.md").write_text(
        "# TEF-RAG v6 Temporal-Hard Benchmark v1\n\n"
        "Status: `UNREVIEWED_CANDIDATE`  \nReview: `PENDING_AI_SEMANTIC_REVIEW`\n\n"
        "This directory contains structurally generated public candidate artifacts. Test gold and canonical flow are excluded and sealed locally. No target retrieval method was run.\n",
        encoding="utf-8",
    )
    public_hashes = {str(path.relative_to(output)).replace("\\", "/"): sha256(path) for path in sorted(output.rglob("*")) if path.is_file() and path.name not in {"manifest.json", "validation_summary.json"}}
    manifest = {
        "dataset_version": config["dataset_version"], "status": config["dataset_status"],
        "review_status": config["review_status"], "protocol_freeze_commit": config["protocol_freeze_commit"],
        "accepted_seed": seed, "generation_attempt": attempt, "public_artifact_hashes": public_hashes,
        "sealed_test_artifact": {"filename": sealed_path.name, "sha256": sha256(sealed_path), "record_count": len(gold_test), "committed": False},
    }
    dump(output / "manifest.json", manifest)
    return generation_summary, gates, manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sealed-output", type=Path, default=DEFAULT_SEALED)
    parser.add_argument("--attempt", type=int, default=0)
    args = parser.parse_args()
    config = load(CONFIG)
    seed = config["attempt_seeds"][args.attempt]
    summary, gates, manifest = write_dataset(args.output, args.sealed_output, config, seed, args.attempt)
    limits = config["gates"]
    accepted = gates["recency_solvable_at_5_rate"] <= limits["challenge_recency_solvable_at_5_max"] and gates["latest5_complete_at_5_rate"] <= limits["challenge_latest5_complete_at_5_max"] and all(row["recency_solvable_at_5_rate"] <= limits["major_stratum_recency_solvable_at_5_max"] for row in gates["major_strata"].values())
    print(json.dumps({"summary": summary, "gates": gates, "sealed_sha256": manifest["sealed_test_artifact"]["sha256"], "accepted": accepted}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if accepted else 2)


if __name__ == "__main__":
    main()
