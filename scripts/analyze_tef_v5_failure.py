"""TEF-RAG v5.1 beam-vs-exact failure attribution on the seen diagnostic set.

Gold and authoring metadata are loaded only after both retrieval variants have
run.  Every gold-dependent field emitted by this script is diagnostic-only and
is not available to the retriever.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline_adapters.query_text_v2 import semantic_question
from scripts.evaluate_tef_v5_holdout_v1 import score as evaluation_score
from scripts.run_tef_shared_complex_v1 import hybrid_scores
from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5


DATA = ROOT / "data/generated/tef_v5_holdout_v3"
PROJECTION = ROOT / "experiments/runs/tef_v5_holdout_projections_v6"
SHARED = ROOT / "experiments/runs/tef_v5_holdout_shared_v1"
OUT = ROOT / "experiments/analyses/tef_v5_1_failure_attribution_v1"
TOP_K = 5
EPSILON = 1e-12
DIAGNOSTIC_WARNING = (
    "DIAGNOSTIC ONLY — NOT AVAILABLE AT RETRIEVAL TIME. "
    "This is a seen diagnostic set. The analysis is for failure attribution and model "
    "development only. It must not be reported as a new unbiased holdout result."
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def lines(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_projections():
    relations = []
    roles = {}
    profiles = {}
    for path in sorted((PROJECTION / "public_graphs").glob("*.json")):
        row = read(path)
        relations.extend(row["relations"])
        for role in row["roles"]:
            roles[role["id"]] = {"role_scores": role["role_scores"]}
    for path in sorted((PROJECTION / "query_profiles").glob("*.json")):
        for profile in read(path)["profiles"]:
            profiles[profile["query_id"]] = {
                "selection_mode": profile["selection_mode"],
                "role_demands": profile["role_demands"],
                "relation_demands": profile["relation_demands"],
            }
    return relations, roles, profiles


def load_authoring():
    cases = {}
    for row in lines(DATA / "authoring/blueprints.jsonl"):
        case_id = row["asset"]["asset_id"]
        identifier_for = row["record_id_map"]
        author_roles = {
            identifier_for[record["record_key"]]: record["author_role"].split("｜", 1)[0]
            for record in row["blueprint"]["records"]
        }
        author_edges = [
            {
                "prior_id": identifier_for[edge["prior"]],
                "update_id": identifier_for[edge["update"]],
                "update_relation": edge["update_relation"],
            }
            for edge in row["blueprint"]["logic_edges"]
        ]
        cases[case_id] = {"author_roles": author_roles, "author_edges": author_edges}
    return cases


def connected_components(nodes, edges):
    nodes = set(nodes)
    adjacency = {node: set() for node in nodes}
    for edge in edges:
        left, right = edge["prior_id"], edge["update_id"]
        if left in nodes and right in nodes:
            adjacency[left].add(right)
            adjacency[right].add(left)
    components = []
    remaining = set(nodes)
    while remaining:
        start = min(remaining)
        stack = [start]
        component = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(sorted(adjacency[node] - component, reverse=True))
        remaining -= component
        components.append(component)
    return sorted(components, key=lambda item: (-len(item), sorted(item)))


def articulation_points(nodes, edges):
    nodes = set(nodes)
    if len(nodes) < 3:
        return set()
    baseline = len(connected_components(nodes, edges))
    points = set()
    for node in nodes:
        reduced = nodes - {node}
        reduced_edges = [
            edge for edge in edges
            if edge["prior_id"] != node and edge["update_id"] != node
        ]
        if reduced and len(connected_components(reduced, reduced_edges)) > baseline:
            points.add(node)
    return points


def structure_metrics(selected_ids, edges, retriever, node_scores, profile):
    selected = set(selected_ids)
    selected_edges = [
        edge for edge in edges
        if edge["prior_id"] in selected and edge["update_id"] in selected
    ]
    components = connected_components(selected, selected_edges)
    directed_pairs = {(edge["prior_id"], edge["update_id"]) for edge in selected_edges}
    covered_roles = sorted({
        role
        for identifier in selected
        for role, value in retriever._role_affinities(identifier).items()
        if value > 0.0
    })
    demanded_roles = set(profile["role_demands"])
    demanded_relation_types = {
        kind for kind, demand in profile["relation_demands"].items() if demand > 0.0
    }
    available_relation_types = {
        edge["update_relation"] for edge in edges
        if edge["update_relation"] in demanded_relation_types
    }
    relation_types = sorted({edge["update_relation"] for edge in selected_edges})
    raw = retriever._raw_components(selected, node_scores, edges, profile, None)
    n = len(selected)
    return {
        "num_connected_components": len(components),
        "largest_connected_evidence_ratio": len(components[0]) / n if n else 0.0,
        "selected_edge_count": len(selected_edges),
        "selected_edge_density": len(directed_pairs) / (n * (n - 1)) if n > 1 else 0.0,
        "covered_roles": covered_roles,
        "role_count": len(covered_roles),
        "role_coverage_score": raw["role"],
        "demanded_roles_complete": demanded_roles <= set(covered_roles),
        "covered_relation_types": relation_types,
        "relation_type_count": len(relation_types),
        "available_demanded_relation_types": sorted(available_relation_types),
        "available_relation_types_complete": available_relation_types <= set(relation_types),
    }


def gold_graph_diagnostics(required_ids, selected_ids, edges):
    required = set(required_ids)
    selected = set(selected_ids)
    gold_edges = [
        edge for edge in edges
        if edge["prior_id"] in required and edge["update_id"] in required
    ]
    components = connected_components(required, gold_edges)
    projected_flows = [component for component in components if len(component) > 1]
    bridges = articulation_points(required, gold_edges)
    degree = {node: 0 for node in required}
    for edge in gold_edges:
        degree[edge["prior_id"]] += 1
        degree[edge["update_id"]] += 1
    endpoints = {node for node, value in degree.items() if value <= 1}
    intermediates = required - endpoints - bridges
    missing = required - selected
    return {
        "projected_gold_edge_count": len(gold_edges),
        "projected_gold_flow_count": len(projected_flows),
        "flow_completion_rate": (
            sum(component <= selected for component in projected_flows) / len(projected_flows)
            if projected_flows else None
        ),
        "required_bridge_ids": sorted(bridges),
        "required_bridge_miss_rate": (
            len(bridges - selected) / len(bridges) if bridges else None
        ),
        "missing_endpoints": sorted(missing & endpoints),
        "missing_bridges": sorted(missing & bridges),
        "missing_intermediate_evidence": sorted(missing & intermediates),
    }


def redundant_extra_nodes(selected_ids, extra_ids, retriever, threshold=0.5):
    redundant = set()
    for left, right in combinations(sorted(selected_ids), 2):
        if retriever._pair_redundancy(left, right, None) >= threshold:
            redundant.update({left, right} & set(extra_ids))
    return sorted(redundant)


def diagnose_method(
    selected_ids,
    required_ids,
    candidate_ids,
    edges,
    retriever,
    node_scores,
    profile,
):
    missing = sorted(set(required_ids) - set(selected_ids))
    extra = sorted(set(selected_ids) - set(required_ids))
    structure = structure_metrics(selected_ids, edges, retriever, node_scores, profile)
    gold_graph = gold_graph_diagnostics(required_ids, selected_ids, edges)
    adjacent_to_gold = {
        endpoint
        for edge in edges
        if edge["prior_id"] in set(required_ids) or edge["update_id"] in set(required_ids)
        for endpoint in (edge["prior_id"], edge["update_id"])
    }
    competing = sorted(set(extra) & adjacent_to_gold)
    flow_incomplete = gold_graph["flow_completion_rate"] not in (None, 1.0)
    return {
        "selected_ids": selected_ids,
        "missing_gold_nodes": missing,
        "extra_nodes": extra,
        "candidate_missing_gold_nodes": sorted(set(required_ids) - set(candidate_ids)),
        **gold_graph,
        "wrong_competing_branch_nodes": competing,
        "redundant_extra_nodes": redundant_extra_nodes(selected_ids, extra, retriever),
        "role_complete_but_flow_incomplete": (
            structure["demanded_roles_complete"] and bool(missing) and flow_incomplete
        ),
        "relation_rich_but_flow_incomplete": (
            structure["selected_edge_count"] >= 2
            and bool(missing)
            and (flow_incomplete or structure["num_connected_components"] > 1)
        ),
        "relation_complete_but_flow_incomplete": (
            structure["available_relation_types_complete"] and bool(missing) and flow_incomplete
        ),
        "structure": structure,
    }


def best_gold_complete_set(candidate_ids, groups, retriever, node_scores, edges, profile):
    """DIAGNOSTIC ONLY: best current-objective Top-k set covering every gold group."""

    records = retriever.by_id
    best = None
    for selected in combinations(sorted(candidate_ids), min(TOP_K, len(candidate_ids))):
        selected_set = frozenset(selected)
        if not all(selected_set & set(group) for group in groups):
            continue
        characters = sum(len(records[identifier].get("text", "")) for identifier in selected)
        if characters > retriever.budget:
            continue
        score = retriever._score_set(selected_set, node_scores, edges, profile, None)
        rank_key = (-score["total"], -score["semantic"], selected)
        if best is None or rank_key < best["rank_key"]:
            best = {
                "selected_ids": list(selected),
                "objective": score["total"],
                "score_components": {
                    key: score[key]
                    for key in ("semantic", "chain", "role", "redundancy", "total")
                },
                "raw_score_components": score["raw"],
                "rank_key": rank_key,
            }
    if best is None:
        return None
    best.pop("rank_key")
    return best


def projection_mismatches(case, required_ids, missing_ids, edges, profile, roles, candidate_ids):
    author_roles = case["author_roles"]
    role_mismatches = []
    profile_missed_roles = []
    for identifier in missing_ids:
        author_role = author_roles.get(identifier)
        projected = roles.get(identifier, {}).get("role_scores", {})
        if author_role and projected.get(author_role, 0.0) < 0.5:
            role_mismatches.append(identifier)
        if author_role and profile["role_demands"].get(author_role, 0.0) == 0.0:
            profile_missed_roles.append(author_role)

    projected_keys = {
        (edge["prior_id"], edge["update_id"], edge["update_relation"])
        for edge in edges
    }
    required = set(required_ids)
    candidates = set(candidate_ids)
    missing_relations = []
    for edge in case["author_edges"]:
        key = (edge["prior_id"], edge["update_id"], edge["update_relation"])
        if (
            edge["prior_id"] in candidates
            and edge["update_id"] in candidates
            and ({edge["prior_id"], edge["update_id"]} & required)
            and key not in projected_keys
        ):
            missing_relations.append(edge)
    return {
        "author_role_projection_mismatch_nodes": sorted(role_mismatches),
        "query_profile_missing_author_roles": sorted(set(profile_missed_roles)),
        "missing_author_relations_in_projection": missing_relations,
    }


def failure_taxonomy(
    beam_diag,
    exact_diag,
    objective_gap,
    exact_margin_over_best_complete,
    mismatches,
):
    if not beam_diag["missing_gold_nodes"]:
        return []
    labels = []
    if objective_gap is not None and objective_gap > EPSILON:
        labels.append("SEARCH_APPROXIMATION")
    if beam_diag["candidate_missing_gold_nodes"]:
        labels.append("SEMANTIC_CANDIDATE_MISS")
    if mismatches["query_profile_missing_author_roles"]:
        labels.append("QUERY_PROFILE_ERROR")
    if mismatches["author_role_projection_mismatch_nodes"]:
        labels.append("ROLE_PROJECTION_ERROR")
    if mismatches["missing_author_relations_in_projection"]:
        labels.append("RELATION_PROJECTION_ERROR")
    if exact_diag["missing_bridges"]:
        labels.append("MISSING_BRIDGE")
    if exact_diag["wrong_competing_branch_nodes"]:
        labels.append("WRONG_BRANCH")
    if exact_diag["redundant_extra_nodes"]:
        labels.append("REDUNDANCY")
    if exact_diag["flow_completion_rate"] not in (None, 1.0):
        labels.append("BROKEN_FLOW")
    if (
        exact_margin_over_best_complete is not None
        and exact_margin_over_best_complete > EPSILON
        and exact_diag["structure"]["num_connected_components"] > 1
    ):
        labels.append("OBJECTIVE_PREFERS_FRAGMENTED_EVIDENCE")
    return labels or ["UNKNOWN"]


def aggregate(rows, predicate):
    selected = [row for row in rows if predicate(row)]
    set_rows = [row for row in selected if row["included_in_search_attribution"]]
    return {
        "queries": len(selected),
        "set_objective_queries": len(set_rows),
        "beam_exact_match_rate": (
            sum(row["beam_equals_exact"] for row in set_rows) / len(set_rows) if set_rows else None
        ),
        "mean_objective_gap": (
            sum(row["objective_gap"] for row in set_rows) / len(set_rows) if set_rows else None
        ),
        "max_objective_gap": max((row["objective_gap"] for row in set_rows), default=None),
        "beam": {
            "recall_at_5": sum(row["beam_recall_at_5"] for row in selected) / len(selected),
            "ndcg_at_5": sum(row["beam_ndcg_at_5"] for row in selected) / len(selected),
            "complete_at_5": sum(row["beam_complete_at_5"] for row in selected) / len(selected),
        },
        "exact": {
            "recall_at_5": sum(row["exact_recall_at_5"] for row in selected) / len(selected),
            "ndcg_at_5": sum(row["exact_ndcg_at_5"] for row in selected) / len(selected),
            "complete_at_5": sum(row["exact_complete_at_5"] for row in selected) / len(selected),
        },
    }


def structural_aggregate(rows, diagnostic_key):
    selected = [row for row in rows if row["included_in_search_attribution"]]
    structures = [row[diagnostic_key]["structure"] for row in selected]
    bridge_rates = [
        row[diagnostic_key]["required_bridge_miss_rate"]
        for row in selected
        if row[diagnostic_key]["required_bridge_miss_rate"] is not None
    ]
    flow_rates = [
        row[diagnostic_key]["flow_completion_rate"]
        for row in selected
        if row[diagnostic_key]["flow_completion_rate"] is not None
    ]
    return {
        "queries": len(selected),
        "mean_connected_components": sum(item["num_connected_components"] for item in structures) / len(structures),
        "mean_largest_connected_evidence_ratio": sum(
            item["largest_connected_evidence_ratio"] for item in structures
        ) / len(structures),
        "mean_selected_edge_count": sum(item["selected_edge_count"] for item in structures) / len(structures),
        "mean_selected_edge_density": sum(item["selected_edge_density"] for item in structures) / len(structures),
        "mean_role_coverage_score": sum(item["role_coverage_score"] for item in structures) / len(structures),
        "mean_required_bridge_miss_rate": sum(bridge_rates) / len(bridge_rates) if bridge_rates else None,
        "bridge_evaluable_queries": len(bridge_rates),
        "mean_flow_completion_rate": sum(flow_rates) / len(flow_rates) if flow_rates else None,
        "flow_evaluable_queries": len(flow_rates),
    }


def render_report(results):
    overall = results["aggregate"]["all"]
    set_scope = results["aggregate"]["set_objective"]
    chain = results["aggregate"]["complex_chain"]
    attribution = results["failure_attribution"]
    taxonomy = results["taxonomy_counts"]
    beam_structure = results["structural_aggregate"]["beam"]
    exact_structure = results["structural_aggregate"]["exact"]
    hybrid_structure = results["structural_aggregate"]["scoped_hybrid"]
    lines_out = [
        "# TEF-RAG v5.1 Failure Attribution",
        "",
        f"> {DIAGNOSTIC_WARNING}",
        "",
        "## Experimental Setup",
        "",
        "The frozen 16-query v5 dataset, candidate IDs, embeddings, query profiles, record roles, and relation projections were reused without regeneration. Beam width is 64 and Top-k is 5. No LLM or external API was called. Latest-control queries use the existing recency mode and are excluded from set-search attribution.",
        "",
        "## Beam vs Exact",
        "",
        "Exact search enumerates every feasible Top-k combination from the identical visible candidate pool and calls the same v5 `score_set` implementation as beam search. Ties use total objective, semantic component, then lexicographically sorted record IDs. Returned order is a deterministic best-prefix serialization.",
        "",
        "| Scope | Set queries | Exact set match | Mean objective gap | Max objective gap | Beam Complete@5 | Exact Complete@5 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| All set-mode | {set_scope['set_objective_queries']} | {set_scope['beam_exact_match_rate']:.4f} | {set_scope['mean_objective_gap']:.12f} | {set_scope['max_objective_gap']:.12f} | {set_scope['beam']['complete_at_5']:.4f} | {set_scope['exact']['complete_at_5']:.4f} |",
        f"| Complex chain | {chain['set_objective_queries']} | {chain['beam_exact_match_rate']:.4f} | {chain['mean_objective_gap']:.12f} | {chain['max_objective_gap']:.12f} | {chain['beam']['complete_at_5']:.4f} | {chain['exact']['complete_at_5']:.4f} |",
        "",
        "## Aggregate Results",
        "",
        "| Scope / selector | Recall@5 | nDCG@5 | Complete@5 |",
        "|---|---:|---:|---:|",
        f"| All / Beam | {overall['beam']['recall_at_5']:.4f} | {overall['beam']['ndcg_at_5']:.4f} | {overall['beam']['complete_at_5']:.4f} |",
        f"| All / Exact | {overall['exact']['recall_at_5']:.4f} | {overall['exact']['ndcg_at_5']:.4f} | {overall['exact']['complete_at_5']:.4f} |",
        f"| Complex / Beam | {chain['beam']['recall_at_5']:.4f} | {chain['beam']['ndcg_at_5']:.4f} | {chain['beam']['complete_at_5']:.4f} |",
        f"| Complex / Exact | {chain['exact']['recall_at_5']:.4f} | {chain['exact']['ndcg_at_5']:.4f} | {chain['exact']['complete_at_5']:.4f} |",
        "",
        "## Per-query Failure Summary",
        "",
        "| Query | Task | Match | Gap | Beam complete | Exact complete | Labels |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in results["per_query"]:
        gap = "n/a" if row["objective_gap"] is None else f"{row['objective_gap']:.12f}"
        lines_out.append(
            f"| {row['query_id']} | {row['task']} | {int(row['beam_equals_exact'])} | {gap} | "
            f"{int(row['beam_complete_at_5'])} | {int(row['exact_complete_at_5'])} | "
            f"{', '.join(row['failure_taxonomy']) or '—'} |"
        )
    lines_out.extend([
        "",
        "## Structural Diagnostics",
        "",
        "`num_connected_components` uses the underlying undirected form of the projected relation graph. Edge density uses unique directed pairs divided by `n*(n-1)`. Role coverage reuses the v5 probability-coverage semantics. `required_bridge_miss_rate` uses articulation points in the projected graph induced by gold nodes; `flow_completion_rate` measures fully covered non-singleton connected components in that same projected-gold graph.",
        "",
        "These bridge and flow values are conservative, projection-conditioned diagnostics. The dataset does not provide a canonical per-query gold chain edge list, so they must not be interpreted as exact ground-truth flow metrics. Null means no defensible projected bridge/flow denominator exists.",
        "",
        "| Selector | Mean components | Mean largest-component ratio | Mean edges | Mean edge density | Mean role coverage | Mean bridge miss rate | Mean flow completion |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| Scoped Hybrid | {hybrid_structure['mean_connected_components']:.4f} | {hybrid_structure['mean_largest_connected_evidence_ratio']:.4f} | {hybrid_structure['mean_selected_edge_count']:.4f} | {hybrid_structure['mean_selected_edge_density']:.4f} | {hybrid_structure['mean_role_coverage_score']:.4f} | {hybrid_structure['mean_required_bridge_miss_rate']:.4f} ({hybrid_structure['bridge_evaluable_queries']} q) | {hybrid_structure['mean_flow_completion_rate']:.4f} ({hybrid_structure['flow_evaluable_queries']} q) |",
        f"| Beam | {beam_structure['mean_connected_components']:.4f} | {beam_structure['mean_largest_connected_evidence_ratio']:.4f} | {beam_structure['mean_selected_edge_count']:.4f} | {beam_structure['mean_selected_edge_density']:.4f} | {beam_structure['mean_role_coverage_score']:.4f} | {beam_structure['mean_required_bridge_miss_rate']:.4f} ({beam_structure['bridge_evaluable_queries']} q) | {beam_structure['mean_flow_completion_rate']:.4f} ({beam_structure['flow_evaluable_queries']} q) |",
        f"| Exact | {exact_structure['mean_connected_components']:.4f} | {exact_structure['mean_largest_connected_evidence_ratio']:.4f} | {exact_structure['mean_selected_edge_count']:.4f} | {exact_structure['mean_selected_edge_density']:.4f} | {exact_structure['mean_role_coverage_score']:.4f} | {exact_structure['mean_required_bridge_miss_rate']:.4f} ({exact_structure['bridge_evaluable_queries']} q) | {exact_structure['mean_flow_completion_rate']:.4f} ({exact_structure['flow_evaluable_queries']} q) |",
        "",
        "## Failure Taxonomy",
        "",
        *(f"- `{label}`: {count}" for label, count in sorted(taxonomy.items())),
        "",
        f"Role-complete but flow-incomplete cases (Exact): {attribution['role_complete_but_flow_incomplete_exact']}.",
        f"Relation-rich but flow-incomplete cases (Exact): {attribution['relation_rich_but_flow_incomplete_exact']}.",
        "",
        "Taxonomy labels are deterministic diagnostic rules, not independently adjudicated causal ground truth. Authoring roles and logic edges are read only by this offline analyzer to surface possible profile/projection mismatches.",
        "",
        "## Main Findings",
        "",
        results["main_finding"],
        "",
        f"Among {attribution['beam_failure_queries']} Beam failures on set-objective queries, Exact resolves {attribution['resolved_by_exact']} and leaves {attribution['persistent_under_exact']} unresolved; {attribution['failures_with_positive_search_gap']} failures have a positive objective gap.",
        f"A gold-complete Top-5 set is feasible for {attribution['failures_with_feasible_gold_complete_set']} of those failures. The exact optimum scores strictly above the best gold-complete set in {attribution['exact_prefers_incomplete_over_best_complete']} cases (mean margin {attribution['mean_exact_margin_over_best_complete']:.4f}). This comparison is diagnostic-only.",
        "",
        "## Implications for v6",
        "",
        results["recommended_next_step"],
        "",
        "## Limitations",
        "",
        "This dataset was already used during development and is not an unbiased holdout. It is small, synthetic, and not independently reviewed. Structural conclusions depend on the frozen public relation and role projections. Required evidence groups are singleton groups, and no canonical per-query gold edge chain is available. Exact search diagnoses the existing objective only; it does not establish that a new objective will generalize.",
        "",
    ])
    return "\n".join(lines_out)


def write_csv(rows):
    fields = [
        "query_id", "case_id", "task", "query", "candidate_count", "top_k",
        "beam_selected_ids", "exact_selected_ids", "beam_objective", "exact_objective",
        "objective_gap", "beam_equals_exact", "beam_recall_at_5", "exact_recall_at_5",
        "beam_ndcg_at_5", "exact_ndcg_at_5", "beam_complete_at_5", "exact_complete_at_5",
        "beam_missing_gold_nodes", "exact_missing_gold_nodes", "beam_extra_nodes", "exact_extra_nodes",
        "failure_taxonomy",
    ]
    with (OUT / "per_query.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {key: row.get(key) for key in fields}
            for key, value in flat.items():
                if isinstance(value, (list, dict)):
                    flat[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            writer.writerow(flat)


def main():
    docs = lines(DATA / "evidence.jsonl")
    queries = lines(DATA / "queries.jsonl")
    assets = read(DATA / "assets.json")
    relations, roles, profiles = load_projections()
    embeddings = np.load(SHARED / "embeddings.npy")
    if embeddings.shape[0] != len(docs) + len(queries):
        raise RuntimeError("frozen embedding row count mismatch")
    doc_vectors = embeddings[: len(docs)]
    query_vectors = embeddings[len(docs) :]

    retriever = QueryConditionedSetEvidenceRetrieverV5(
        docs, assets, relations, roles=roles, top_k=TOP_K, beam_width=64
    )
    frozen = {
        path.stem: read(path)
        for path in sorted((SHARED / "queries").glob("*.json"))
    }
    if set(frozen) != {query["query_id"] for query in queries}:
        raise RuntimeError("frozen shared output coverage mismatch")

    # Retrieval phase: no gold or authoring files have been read above this line.
    retrieval_rows = []
    for query_index, query in enumerate(queries):
        frozen_row = frozen[query["query_id"]]
        candidate_ids = frozen_row["candidate_ids"]
        pool = [index for index, doc in enumerate(docs) if doc["id"] in set(candidate_ids)]
        relevance_values = hybrid_scores(
            docs,
            pool,
            semantic_question(query["text"]),
            doc_vectors,
            query_vectors[query_index],
        )
        relevance = {doc["id"]: float(relevance_values[index]) for index, doc in enumerate(docs)}
        profile = profiles[query["query_id"]]
        beam = retriever.retrieve(query, relevance, query_profile=profile, search_strategy="beam")
        exact = retriever.retrieve(query, relevance, query_profile=profile, search_strategy="exact")
        if beam["evidence_ids"] != frozen_row["methods"]["tef_v5"]["evidence_ids"]:
            raise RuntimeError(f"beam reproduction mismatch: {query['query_id']}")
        if set(beam["evidence_ids"]) - set(candidate_ids) or set(exact["evidence_ids"]) - set(candidate_ids):
            raise RuntimeError(f"candidate scope violation: {query['query_id']}")
        _, candidates = retriever.base.scope(query)
        if {item["id"] for item in candidates} != set(candidate_ids):
            raise RuntimeError(f"visible candidate mismatch: {query['query_id']}")
        node_scores = retriever._normalise_relevance(candidates, relevance)
        edges, rejected = retriever._admissible_edges_v5(candidates, None)
        retrieval_rows.append({
            "query": query,
            "candidate_ids": candidate_ids,
            "scoped_hybrid_ids": frozen_row["methods"]["scoped_hybrid"]["evidence_ids"],
            "beam": beam,
            "exact": exact,
            "node_scores": node_scores,
            "edges": edges,
            "rejected_edges": rejected,
        })

    # DIAGNOSTIC ONLY — gold and authoring data enter only after retrieval is complete.
    gold = {row["query_id"]: row for row in lines(DATA / "evaluation/gold.jsonl")}
    authoring = load_authoring()
    per_query = []
    taxonomy_counts = Counter()
    for retrieval in retrieval_rows:
        query = retrieval["query"]
        query_id = query["query_id"]
        gold_row = gold[query_id]
        required_ids = [item for group in gold_row["required_evidence_groups"] for item in group]
        beam = retrieval["beam"]
        exact = retrieval["exact"]
        normalized_profile = beam["query_profile"]
        is_set = normalized_profile["selection_mode"] == "set"
        beam_metric = evaluation_score(beam["evidence_ids"], gold_row["required_evidence_groups"])
        exact_metric = evaluation_score(exact["evidence_ids"], gold_row["required_evidence_groups"])
        beam_objective = beam.get("score_components", {}).get("total") if is_set else None
        exact_objective = exact.get("score_components", {}).get("total") if is_set else None
        objective_gap = exact_objective - beam_objective if is_set else None
        if objective_gap is not None and objective_gap < -EPSILON:
            raise RuntimeError(f"exact objective below beam: {query_id}")
        beam_diag = diagnose_method(
            beam["evidence_ids"], required_ids, retrieval["candidate_ids"], retrieval["edges"],
            retriever, retrieval["node_scores"], normalized_profile,
        )
        exact_diag = diagnose_method(
            exact["evidence_ids"], required_ids, retrieval["candidate_ids"], retrieval["edges"],
            retriever, retrieval["node_scores"], normalized_profile,
        )
        hybrid_diag = diagnose_method(
            retrieval["scoped_hybrid_ids"], required_ids, retrieval["candidate_ids"], retrieval["edges"],
            retriever, retrieval["node_scores"], normalized_profile,
        )
        best_complete = (
            best_gold_complete_set(
                retrieval["candidate_ids"], gold_row["required_evidence_groups"], retriever,
                retrieval["node_scores"], retrieval["edges"], normalized_profile,
            )
            if is_set else None
        )
        exact_margin_over_best_complete = (
            exact_objective - best_complete["objective"]
            if is_set and best_complete is not None else None
        )
        mismatches = projection_mismatches(
            authoring[gold_row["case_id"]], required_ids, exact_diag["missing_gold_nodes"],
            retrieval["edges"], normalized_profile, roles, retrieval["candidate_ids"],
        )
        taxonomy = failure_taxonomy(
            beam_diag,
            exact_diag,
            objective_gap,
            exact_margin_over_best_complete,
            mismatches,
        )
        taxonomy_counts.update(taxonomy)
        per_query.append({
            "diagnostic_only": True,
            "query_id": query_id,
            "case_id": gold_row["case_id"],
            "task": gold_row["task"],
            "query": query["text"],
            "candidate_count": len(retrieval["candidate_ids"]),
            "candidate_ids": retrieval["candidate_ids"],
            "top_k": TOP_K,
            "selection_mode": normalized_profile["selection_mode"],
            "included_in_search_attribution": is_set,
            "gold_evidence_groups": gold_row["required_evidence_groups"],
            "scoped_hybrid_selected_ids": retrieval["scoped_hybrid_ids"],
            "beam_selected_ids": beam["evidence_ids"],
            "exact_selected_ids": exact["evidence_ids"],
            "beam_objective": beam_objective,
            "exact_objective": exact_objective,
            "objective_gap": objective_gap,
            "best_gold_complete_set": best_complete,
            "exact_margin_over_best_complete": exact_margin_over_best_complete,
            "beam_equals_exact": set(beam["evidence_ids"]) == set(exact["evidence_ids"]),
            "beam_recall_at_5": beam_metric["group_recall_at_5"],
            "exact_recall_at_5": exact_metric["group_recall_at_5"],
            "beam_ndcg_at_5": beam_metric["binary_ndcg_at_5"],
            "exact_ndcg_at_5": exact_metric["binary_ndcg_at_5"],
            "beam_complete_at_5": beam_metric["complete_at_5"],
            "exact_complete_at_5": exact_metric["complete_at_5"],
            "beam_missing_gold_nodes": beam_diag["missing_gold_nodes"],
            "exact_missing_gold_nodes": exact_diag["missing_gold_nodes"],
            "beam_extra_nodes": beam_diag["extra_nodes"],
            "exact_extra_nodes": exact_diag["extra_nodes"],
            "beam_diagnostics": beam_diag,
            "exact_diagnostics": exact_diag,
            "scoped_hybrid_diagnostics": hybrid_diag,
            "projection_diagnostics": mismatches,
            "failure_taxonomy": taxonomy,
        })

    aggregate_results = {
        "all": aggregate(per_query, lambda row: True),
        "set_objective": aggregate(per_query, lambda row: row["included_in_search_attribution"]),
        "complex_chain": aggregate(per_query, lambda row: row["task"] == "complex_chain"),
        "cutoff_sensitive": aggregate(per_query, lambda row: row["task"] == "cutoff_sensitive"),
        "latest_control": aggregate(per_query, lambda row: row["task"] == "latest_control"),
    }
    set_failures = [
        row for row in per_query
        if row["included_in_search_attribution"] and not row["beam_complete_at_5"]
    ]
    resolved = sum(row["exact_complete_at_5"] for row in set_failures)
    persistent = sum(not row["exact_complete_at_5"] for row in set_failures)
    positive_gap = sum((row["objective_gap"] or 0.0) > EPSILON for row in set_failures)
    feasible_complete = [row for row in set_failures if row["best_gold_complete_set"] is not None]
    preferred_incomplete = [
        row for row in feasible_complete
        if (row["exact_margin_over_best_complete"] or 0.0) > EPSILON
    ]
    if positive_gap == 0:
        main_finding = (
            "Exact and Beam select the same objective-optimal sets on every set-mode query. "
            "The observed Complete@5 failures therefore cannot be attributed to beam approximation "
            "on this diagnostic set."
        )
        next_step = (
            "Search is not the primary issue on these 8/12-candidate pools. The next stage should "
            "investigate a preregistered closure-/flow-completion-aware v6 objective and independently "
            "validate it, without tuning on this seen set."
        )
    elif resolved and persistent:
        main_finding = (
            "Failure sources are mixed: Exact repairs some Beam failures, while other failures persist "
            "under the exact optimum of the current objective."
        )
        next_step = (
            "Quantify both strata separately: improve combinatorial search for search-resolved cases, "
            "and preregister a flow-aware objective study for failures persistent under Exact."
        )
    elif resolved:
        main_finding = "Exact materially repairs Beam failures, making search approximation a primary cause."
        next_step = (
            "Prioritize exact or improved combinatorial search before changing the scoring objective."
        )
    else:
        main_finding = (
            "Beam sometimes misses the objective optimum, but those objective gains do not repair "
            "Complete@5 failures; objective expressiveness remains the dominant observed limitation."
        )
        next_step = (
            "Retain search-gap monitoring, but prioritize a preregistered flow-aware objective study."
        )

    attribution = {
        "beam_failure_queries": len(set_failures),
        "resolved_by_exact": int(resolved),
        "persistent_under_exact": int(persistent),
        "failures_with_positive_search_gap": int(positive_gap),
        "failures_with_feasible_gold_complete_set": len(feasible_complete),
        "exact_prefers_incomplete_over_best_complete": len(preferred_incomplete),
        "mean_exact_margin_over_best_complete": (
            sum(row["exact_margin_over_best_complete"] for row in feasible_complete)
            / len(feasible_complete)
            if feasible_complete else None
        ),
        "role_complete_but_flow_incomplete_exact": sum(
            row["exact_diagnostics"]["role_complete_but_flow_incomplete"] for row in set_failures
        ),
        "relation_rich_but_flow_incomplete_exact": sum(
            row["exact_diagnostics"]["relation_rich_but_flow_incomplete"] for row in set_failures
        ),
    }
    results = {
        "title": "TEF-RAG v5.1 Failure Attribution",
        "diagnostic_only": True,
        "warning": DIAGNOSTIC_WARNING,
        "retrieval_gold_free": True,
        "llm_calls": 0,
        "top_k": TOP_K,
        "beam_width": 64,
        "tie_break": "total_objective_desc,semantic_desc,sorted_record_ids_asc",
        "aggregate": aggregate_results,
        "structural_aggregate": {
            "scoped_hybrid": structural_aggregate(per_query, "scoped_hybrid_diagnostics"),
            "beam": structural_aggregate(per_query, "beam_diagnostics"),
            "exact": structural_aggregate(per_query, "exact_diagnostics"),
        },
        "failure_attribution": attribution,
        "taxonomy_counts": dict(sorted(taxonomy_counts.items())),
        "main_finding": main_finding,
        "recommended_next_step": next_step,
        "per_query": per_query,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(per_query)
    (OUT / "report.md").write_text(render_report(results), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT.relative_to(ROOT)),
        "set_queries": aggregate_results["set_objective"]["queries"],
        "beam_exact_match_rate": aggregate_results["set_objective"]["beam_exact_match_rate"],
        "mean_objective_gap": aggregate_results["set_objective"]["mean_objective_gap"],
        "beam_complete_at_5": aggregate_results["complex_chain"]["beam"]["complete_at_5"],
        "exact_complete_at_5": aggregate_results["complex_chain"]["exact"]["complete_at_5"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
