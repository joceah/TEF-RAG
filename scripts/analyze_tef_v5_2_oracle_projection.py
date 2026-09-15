"""Offline 2x2x2 oracle projection attribution for frozen TEF-RAG v5.

This module is deliberately an analyzer, not a retriever. Gold and authoring
metadata are used only to construct counterfactual profile/role/relation
projections. Every condition keeps the frozen candidates, semantic scores,
Top-k, budget, exact search, and ``QueryConditionedSetEvidenceRetrieverV5``
set objective.
"""
from __future__ import annotations

import csv
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline_adapters.query_text_v2 import semantic_question
from scripts.analyze_tef_v5_failure import (
    DIAGNOSTIC_WARNING,
    lines,
    load_authoring,
    load_projections,
    read,
    structure_metrics,
)
from scripts.evaluate_tef_v5_holdout_v1 import score as evaluation_score
from scripts.run_tef_shared_complex_v1 import hybrid_scores
from tef_rag_v1.retriever import RELATIONS
from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5

DATA = ROOT / "data/generated/tef_v5_holdout_v3"
PROJECTION = ROOT / "experiments/runs/tef_v5_holdout_projections_v6"
SHARED = ROOT / "experiments/runs/tef_v5_holdout_shared_v1"
V51 = ROOT / "experiments/analyses/tef_v5_1_failure_attribution_v1/results.json"
OUT = ROOT / "experiments/analyses/tef_v5_2_oracle_projection_attribution_v1"
TOP_K = 5

CONFIGURATIONS = tuple(
    "".join("O" if enabled else "C" for enabled in switches)
    for switches in product((False, True), repeat=3)
)


def oracle_roles(authoring):
    """Map the explicit author-role prefix to the existing open role ontology."""
    return {
        identifier: {"role_scores": {role: 1.0}}
        for case in authoring.values()
        for identifier, role in case["author_roles"].items()
    }


def oracle_relations(case, candidate_ids):
    """Keep explicit author edges whose endpoints remain in visible scope."""
    scope = set(candidate_ids)
    return [
        {**edge, "confidence": 1.0}
        for edge in case["author_edges"]
        if edge["prior_id"] in scope
        and edge["update_id"] in scope
        and edge["prior_id"] != edge["update_id"]
        and edge["update_relation"] in RELATIONS
    ]


def oracle_profile(current, case, required_ids):
    """Derive deterministic demands only from required nodes and authored edges."""
    required = set(required_ids)
    demanded_roles = sorted({case["author_roles"][item] for item in required})
    demanded_relations = sorted({
        edge["update_relation"]
        for edge in case["author_edges"]
        if edge["prior_id"] in required
        and edge["update_id"] in required
        and edge["update_relation"] in RELATIONS
    })
    # No invented demand: retain the current field when the authoring graph does
    # not state a canonical relation between this query's required nodes.
    relation_demands = (
        {kind: 1.0 for kind in demanded_relations}
        if demanded_relations else dict(current["relation_demands"])
    )
    return {
        "selection_mode": "set",
        "role_demands": {role: 1.0 for role in demanded_roles},
        "relation_demands": relation_demands,
        "relation_fallback_to_current": not bool(demanded_relations),
    }


def build_inputs():
    docs = lines(DATA / "evidence.jsonl")
    queries = lines(DATA / "queries.jsonl")
    assets = read(DATA / "assets.json")
    current_relations, current_roles, profiles = load_projections()
    authoring = load_authoring()
    gold = {row["query_id"]: row for row in lines(DATA / "evaluation/gold.jsonl")}
    frozen = {p.stem: read(p) for p in sorted((SHARED / "queries").glob("*.json"))}
    embeddings = np.load(SHARED / "embeddings.npy")
    doc_vectors = embeddings[:len(docs)]
    query_vectors = embeddings[len(docs):]
    return (docs, queries, assets, current_relations, current_roles, profiles,
            authoring, gold, frozen, doc_vectors, query_vectors)


def aggregate(rows, scope):
    selected = [row for row in rows if scope(row)]
    output = {}
    for code in CONFIGURATIONS:
        config_rows = [r for r in selected if r["configuration"] == code]
        repaired = sum(r["complete_repaired"] for r in config_rows)
        regressed = sum(r["complete_regressed"] for r in config_rows)
        output[code] = {
            "queries": len(config_rows),
            "complete_count": sum(r["complete_at_5"] for r in config_rows),
            "recall_at_5": sum(r["recall_at_5"] for r in config_rows) / len(config_rows),
            "ndcg_at_5": sum(r["ndcg_at_5"] for r in config_rows) / len(config_rows),
            "complete_at_5": sum(r["complete_at_5"] for r in config_rows) / len(config_rows),
            "repaired_failures": repaired,
            "regressed_successes": regressed,
            "net_complete_gain": repaired - regressed,
        }
    return output


def run():
    (docs, queries, assets, current_relations, current_roles, profiles,
     authoring, gold, frozen, doc_vectors, query_vectors) = build_inputs()
    all_oracle_roles = oracle_roles(authoring)
    rows = []
    for query_index, query in enumerate(queries):
        current_profile = profiles[query["query_id"]]
        if current_profile["selection_mode"] != "set":
            continue
        gold_row = gold[query["query_id"]]
        case = authoring[gold_row["case_id"]]
        required_ids = [item for group in gold_row["required_evidence_groups"] for item in group]
        candidate_ids = frozen[query["query_id"]]["candidate_ids"]
        pool = [i for i, doc in enumerate(docs) if doc["id"] in set(candidate_ids)]
        values = hybrid_scores(docs, pool, semantic_question(query["text"]), doc_vectors, query_vectors[query_index])
        relevance = {doc["id"]: float(values[i]) for i, doc in enumerate(docs)}
        op = oracle_profile(current_profile, case, required_ids)
        baseline_selected = None
        baseline_complete = None
        for profile_oracle, roles_oracle, relations_oracle in product((False, True), repeat=3):
            code = "".join("O" if x else "C" for x in (profile_oracle, roles_oracle, relations_oracle))
            relations = oracle_relations(case, candidate_ids) if relations_oracle else current_relations
            roles = all_oracle_roles if roles_oracle else current_roles
            profile = dict(op if profile_oracle else current_profile)
            profile.pop("relation_fallback_to_current", None)
            retriever = QueryConditionedSetEvidenceRetrieverV5(docs, assets, relations, roles=roles, top_k=TOP_K, beam_width=64)
            result = retriever.retrieve(query, relevance, query_profile=profile, search_strategy="exact")
            if set(result["evidence_ids"]) - set(candidate_ids):
                raise RuntimeError(f"candidate scope violation: {query['query_id']} {code}")
            metric = evaluation_score(result["evidence_ids"], gold_row["required_evidence_groups"])
            if code == "CCC":
                baseline_selected = result["evidence_ids"]
                baseline_complete = metric["complete_at_5"]
                v51 = frozen[query["query_id"]]["methods"]["tef_v5"]["evidence_ids"]
                if set(baseline_selected) != set(v51):
                    raise RuntimeError(f"CCC does not reproduce v5.1: {query['query_id']}")
            missing = sorted(set(required_ids) - set(result["evidence_ids"]))
            extra = sorted(set(result["evidence_ids"]) - set(required_ids))
            _, candidates = retriever.base.scope(query)
            node_scores = retriever._normalise_relevance(candidates, relevance)
            edges, _ = retriever._admissible_edges_v5(candidates, None)
            structure = structure_metrics(result["evidence_ids"], edges, retriever, node_scores, result["query_profile"])
            rows.append({
                "query_id": query["query_id"], "case_id": gold_row["case_id"], "task": gold_row["task"],
                "candidate_count": len(candidate_ids), "configuration": code,
                "profile": "oracle" if profile_oracle else "current",
                "roles": "oracle" if roles_oracle else "current",
                "relations": "oracle" if relations_oracle else "current",
                "selected_ids": result["evidence_ids"],
                "objective_total": result["score_components"]["total"],
                **{key: result["score_components"][key] for key in ("semantic", "chain", "role", "redundancy")},
                "recall_at_5": metric["group_recall_at_5"], "ndcg_at_5": metric["binary_ndcg_at_5"],
                "complete_at_5": metric["complete_at_5"], "missing_gold_nodes": missing, "extra_nodes": extra,
                "current_vs_oracle_selection_changed": set(result["evidence_ids"]) != set(baseline_selected or result["evidence_ids"]),
                "complete_repaired": bool(metric["complete_at_5"] and not baseline_complete) if baseline_complete is not None else False,
                "complete_regressed": bool(not metric["complete_at_5"] and baseline_complete) if baseline_complete is not None else False,
                "oracle_profile_relation_fallback": bool(profile_oracle and op["relation_fallback_to_current"]),
                "num_connected_components": structure["num_connected_components"],
                "largest_component_ratio": structure["largest_connected_evidence_ratio"],
                "edge_count": structure["selected_edge_count"], "role_coverage": structure["role_coverage_score"],
            })
    # Since CCC is emitted first for every query, repair/change flags are now valid.
    summary = {"all_set_mode": aggregate(rows, lambda r: True),
               "complex_chain": aggregate(rows, lambda r: r["task"] == "complex_chain")}
    ccc_failures = {r["query_id"] for r in rows if r["configuration"] == "CCC" and not r["complete_at_5"]}
    ooo_residual = [r for r in rows if r["configuration"] == "OOO" and r["query_id"] in ccc_failures and not r["complete_at_5"]]
    results = {
        "title": "TEF-RAG v5.2 Oracle Projection Attribution", "diagnostic_only": True,
        "warning": DIAGNOSTIC_WARNING, "retrieval_gold_free": False, "llm_calls": 0,
        "factor_order": ["profile", "roles", "relations"], "configurations": list(CONFIGURATIONS),
        "frozen": ["candidate_pool", "visibility", "semantic_scores", "top_k", "budget", "objective_weights", "_score_set", "exact_search", "gold", "evaluation"],
        "oracle_role_mapping": "author_role prefix -> identical open role label with probability 1.0",
        "summary": summary, "ccc_failures": len(ccc_failures),
        "ooo_residual_failures": len(ooo_residual), "ooo_residual_query_ids": [r["query_id"] for r in ooo_residual],
        "per_query": rows,
    }
    return results


def write_outputs(results):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["query_id", "case_id", "task", "candidate_count", "configuration", "profile", "roles", "relations",
              "selected_ids", "objective_total", "semantic", "chain", "role", "redundancy", "recall_at_5", "ndcg_at_5",
              "complete_at_5", "missing_gold_nodes", "extra_nodes", "current_vs_oracle_selection_changed", "complete_repaired", "complete_regressed",
              "num_connected_components", "largest_component_ratio", "edge_count", "role_coverage", "oracle_profile_relation_fallback"]
    with (OUT / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for row in results["per_query"]:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=False) if isinstance(row[k], list) else row[k] for k in fields})
    with (OUT / "configuration_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields2 = ["scope", "configuration", "profile", "roles", "relations", "queries", "complete_count", "recall_at_5", "ndcg_at_5", "complete_at_5", "repaired_failures", "regressed_successes", "net_complete_gain"]
        writer = csv.DictWriter(handle, fieldnames=fields2); writer.writeheader()
        for scope, table in results["summary"].items():
            for code, values in table.items():
                writer.writerow({"scope": scope, "configuration": code, "profile": code[0], "roles": code[1], "relations": code[2], **values})
    (OUT / "report.md").write_text(render_report(results), encoding="utf-8")


def render_report(results):
    def table(scope):
        out = ["| Profile | Roles | Relations | Recall@5 | nDCG@5 | Complete@5 | repaired failures | regressed successes | net Complete gain |",
               "|---|---|---|---:|---:|---:|---:|---:|---:|"]
        for code, row in results["summary"][scope].items():
            out.append(f"| {'oracle' if code[0]=='O' else 'current'} | {'oracle' if code[1]=='O' else 'current'} | {'oracle' if code[2]=='O' else 'current'} | {row['recall_at_5']:.4f} | {row['ndcg_at_5']:.4f} | {row['complete_at_5']:.4f} | {row['repaired_failures']} | {row['regressed_successes']} | {row['net_complete_gain']:+d} |")
        return "\n".join(out)
    all_s = results["summary"]["all_set_mode"]
    alone = {"Profile": all_s["OCC"], "Roles": all_s["COC"], "Relations": all_s["CCO"]}
    accounting = ", ".join(
        f"{k}: repaired {v['repaired_failures']}, regressed {v['regressed_successes']}, net {v['net_complete_gain']:+d}"
        for k, v in alone.items()
    )
    return f"""# TEF-RAG v5.2 Oracle Projection Attribution

> {DIAGNOSTIC_WARNING}

## Setup

Offline 2×2×2 counterfactual attribution on the 12 seen set-mode queries. Candidate pools, bitemporal visibility, semantic scores, Top-k=5, character budget, frozen v5 weights, `_score_set`, exact search, gold definition, and evaluation are unchanged. Latest-control is excluded. No LLM was called. Oracle metadata exists only in this analyzer and is not a realizable retrieval graph.

Oracle roles use the explicit author-role prefix with probability 1. Oracle relations retain only explicit authoring edges whose endpoints are inside the unchanged visible candidate pool. Oracle profile demands the unique authored roles of required evidence and explicit relation types connecting required nodes; where no such relation exists, that field stays current and is flagged in the outputs.

## All set-mode

{table('all_set_mode')}

## Complex chain

{table('complex_chain')}

## Attribution answers

- Oracle Profile alone repairs {alone['Profile']['repaired_failures']} prior failure(s), regresses {alone['Profile']['regressed_successes']} prior success(es), net Complete gain {alone['Profile']['net_complete_gain']:+d}.
- Oracle Roles alone repairs {alone['Roles']['repaired_failures']} prior failure(s), but also regresses {alone['Roles']['regressed_successes']} prior success(es), net Complete gain {alone['Roles']['net_complete_gain']:+d}.
- Oracle Relations alone repairs {alone['Relations']['repaired_failures']} prior failure(s), regresses {alone['Relations']['regressed_successes']} prior success(es), net Complete gain {alone['Relations']['net_complete_gain']:+d}.
- Single-factor gross/net accounting: {accounting}. Compare the paired and OOO rows above for interactions.
- OOO leaves {results['ooo_residual_failures']} of {results['ccc_failures']} original incomplete queries incomplete: {', '.join(results['ooo_residual_query_ids']) or 'none'}.

OOO residuals are direct evidence that a gold-complete Top-5 remains feasible while the frozen exact objective prefers an incomplete set under the strongest defensible authoring-derived representation. Thus residual failure is objective-misalignment evidence on this seen diagnostic set; it is not an independent validation result.

## Decision

Interpretation follows the frozen rule: large oracle-representation repair favors graph/projection work; substantial OOO residual failure favors objective/flow-completion work; both together imply both must be addressed. Detailed per-query selections and components are in `per_query.csv` and `results.json`.
"""


def main():
    results = run(); write_outputs(results)
    print(json.dumps({"out": str(OUT.relative_to(ROOT)), "ccc": results["summary"]["all_set_mode"]["CCC"], "ooo": results["summary"]["all_set_mode"]["OOO"], "ooo_residual": results["ooo_residual_failures"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
