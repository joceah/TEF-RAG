"""Serialize hand-authored pilot semantics; this module does not generate scenarios."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/generated/tef_v6_authoring_pilot_v1"
AUTHORED = BASE / "authoring/pilot_authored_chains.jsonl"
REVIEW = ROOT / "experiments/analyses/tef_v6_authoring_pilot_v1/review_book.md"


def dump(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")


def main():
    authored = [json.loads(line) for line in AUTHORED.read_text(encoding="utf-8").splitlines() if line.strip()]
    chains, evidence_rows, queries, gold = [], [], [], []
    review = ["# TEF-RAG v6 Authoring Pilot v1 Review Book", "", "Status: `AUTHORING_PILOT_UNREVIEWED`", "", "Review: `PENDING_USER_AND_CHATGPT_REVIEW`", ""]
    for ci, item in enumerate(authored, 1):
        chain_id = f"PILOT-C{ci:02d}"
        asset_id = f"PILOT-A{ci:02d}"
        key_to_id = {row[0]: f"{chain_id}-E{ei:02d}" for ei, row in enumerate(item["evidence"], 1)}
        chain_query_ids = []
        for ei, row in enumerate(item["evidence"], 1):
            key, event_time, source, event_type, text, episode, *rest = row
            evidence_rows.append({"evidence_id": key_to_id[key], "chain_id": chain_id, "asset_id": asset_id,
                "source_type": source, "event_type": event_type, "event_time": event_time,
                "available_at": rest[0] if rest else event_time, "episode_id": f"{chain_id}-{episode}", "text": text})
        for qi, q in enumerate(item["queries"], 1):
            intent, query_time, text, groups, edges = q
            query_id = f"{chain_id}-Q{qi:02d}"
            chain_query_ids.append(query_id)
            queries.append({"query_id": query_id, "intent_id": f"{chain_id}-{intent}", "chain_id": chain_id,
                "asset_id": asset_id, "partition": "AUTHORING_PILOT", "query_time": query_time, "query_text": text})
            out_groups = [{"group_id": f"{query_id}-G{gi:02d}-{name}", "role": name,
                           "acceptable_evidence_ids": [key_to_id[k] for k in keys]}
                          for gi, (name, keys) in enumerate(groups, 1)]
            group_ids = {name: g["group_id"] for (name, _), g in zip(groups, out_groups)}
            out_edges = []
            for gi, (src, dst, pairs) in enumerate(edges, 1):
                out_edges.append({"edge_id": f"{query_id}-F{gi:02d}", "from_group": group_ids[src],
                    "to_group": group_ids[dst], "relation_type": "supports_next",
                    "allowed_endpoint_pairs": [[key_to_id[a], key_to_id[b]] for a, b in pairs]})
            gold.append({"query_id": query_id, "chain_id": chain_id, "required_groups": out_groups,
                "required_flow_edges": out_edges, "persistent_uncertainty": item["difficulty"] == "PERSISTENT_UNCERTAINTY"})
        chains.append({"chain_id": chain_id, "asset_id": asset_id, "asset_context": item["asset"],
            "chain_summary": item["summary"], "difficulty_labels": [item["difficulty"]],
            "scenario_family_id": item["slug"], "template_family_id": "HAND_AUTHORED_NO_TEMPLATE",
            "partition": "AUTHORING_PILOT", "query_ids": chain_query_ids,
            "flowcomplete_ambiguous_possible": bool(item["ambiguous"]), "source_basis_ids": ["SRC-HITHIUM-280AH"],
            "source_basis_note": item["source_note"], "modeling_choices": ["synthetic operational semantics"]})
        review += [f"## {chain_id} — {item['difficulty']}", "", f"- Asset: {item['asset']}",
                   f"- Summary: {item['summary']}", "", "Timeline:", ""]
        review += [f"- {r[1]} · {r[2]} · {r[4]}" for r in item["evidence"]]
        review += ["", "Queries:", ""] + [f"- {q[1]} · {q[2]}" for q in item["queries"]]
        for qrow, grow in zip(item["queries"], gold[-len(item["queries"]):]):
            review += ["", f"Required groups / canonical flow ({qrow[0]}):", "",
                "- Groups: " + "; ".join(f"{g['role']}=[{', '.join(g['acceptable_evidence_ids'])}]" for g in grow["required_groups"]),
                "- Flow: " + " ; ".join(f"{e['from_group']} → {e['to_group']}" for e in grow["required_flow_edges"])]
        review.append("")
    dump(BASE / "chains/pilot_chains.jsonl", chains)
    dump(BASE / "evidence/pilot_evidence.jsonl", evidence_rows)
    dump(BASE / "queries/pilot_queries.jsonl", queries)
    dump(BASE / "gold/pilot_gold.jsonl", gold)
    registry = [{"source_basis_id": "SRC-HITHIUM-280AH", "name": "HiTHIUM V1.1 ESS Cell 280 Ah datasheet",
        "url": "https://hithium.com/fileadmin/ns_theme_hithium/pdf/HiTHIUM_Data-Sheet_ESS-Cell280Ah_V1-1_EU_EN_230612.pdf",
        "supports": ["280Ah-class LFP reference", "3.2V nominal", "operating voltage and ambient-temperature envelope"],
        "note": "Operational causal stories and thresholds not explicitly sourced are labeled MODELING_CHOICE."}]
    (BASE / "metadata").mkdir(parents=True, exist_ok=True)
    (BASE / "metadata/source_registry.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    counts = Counter(c["difficulty_labels"][0] for c in chains)
    manifest = {"dataset_id": "TEF_RAG_v6_authoring_pilot_v1", "pilot_status": "AUTHORING_PILOT_UNREVIEWED",
        "review_status": "PENDING_USER_AND_CHATGPT_REVIEW", "partition": "AUTHORING_PILOT",
        "counts": {"chains": len(chains), "evidence": len(evidence_rows), "queries": len(queries),
                   "intents": len({q['intent_id'] for q in queries}), "flowcomplete_ambiguous_chains": sum(c["flowcomplete_ambiguous_possible"] for c in chains)},
        "difficulty_distribution": dict(sorted(counts.items())), "authored_source_sha256": hashlib.sha256(AUTHORED.read_bytes()).hexdigest()}
    (BASE / "metadata/pilot_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text("\n".join(review), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
