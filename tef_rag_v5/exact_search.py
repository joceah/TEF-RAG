"""Deterministic exhaustive search for the TEF-RAG v5 set objective.

The solver is deliberately objective-agnostic.  It receives the same
``score_set`` callback used by beam search and never receives gold labels.
"""

from __future__ import annotations

from itertools import combinations


def _best_prefix_order(selected_ids, score_set):
    """Choose a deterministic insertion order without changing the set."""

    states = {frozenset(): (tuple(), tuple())}
    selected = frozenset(selected_ids)
    for _ in range(len(selected)):
        next_states = {}
        for present, (sequence, prefix_scores) in states.items():
            for identifier in sorted(selected - present):
                new_sequence = sequence + (identifier,)
                new_present = frozenset(new_sequence)
                candidate = (
                    new_sequence,
                    prefix_scores + (score_set(new_present)["total"],),
                )
                incumbent = next_states.get(new_present)
                if incumbent is None:
                    next_states[new_present] = candidate
                    continue
                if candidate[1] > incumbent[1] or (
                    candidate[1] == incumbent[1] and candidate[0] < incumbent[0]
                ):
                    next_states[new_present] = candidate
        states = next_states
    return states[selected][0]


def exact_set_search(candidate_records, top_k, budget, score_set):
    """Return the exact best feasible set under an existing set objective.

    Full ``top_k`` sets are preferred.  If the character budget makes all of
    them infeasible, the largest feasible cardinality is used, matching the
    beam selector's maximum-depth behavior.

    Ties are resolved by total objective, then semantic component, then the
    lexicographically sorted record IDs.  The selected set is returned in the
    deterministic best-prefix order used for trace/ranking serialization.
    """

    records = {record["id"]: record for record in candidate_records}
    ordered_ids = tuple(sorted(records))
    evaluated_sets = 0
    best = None

    for size in range(min(int(top_k), len(ordered_ids)), -1, -1):
        feasible_at_size = False
        for selected in combinations(ordered_ids, size):
            characters = sum(len(records[identifier].get("text", "")) for identifier in selected)
            if characters > budget:
                continue
            feasible_at_size = True
            components = score_set(frozenset(selected))
            evaluated_sets += 1
            rank_key = (-components["total"], -components["semantic"], selected)
            if best is None or rank_key < best["rank_key"]:
                best = {
                    "selected_ids": selected,
                    "characters": characters,
                    "score_components": components,
                    "rank_key": rank_key,
                }
        if feasible_at_size:
            break

    if best is None:  # Defensive only: the empty set is always budget-feasible.
        raise RuntimeError("exact search found no feasible set")

    sequence = _best_prefix_order(best["selected_ids"], score_set)
    return {
        "sequence": sequence,
        "selected_ids": tuple(sorted(best["selected_ids"])),
        "objective_score": best["score_components"]["total"],
        "score_breakdown": {
            key: best["score_components"][key]
            for key in ("semantic", "chain", "role", "redundancy", "total")
        },
        "characters": best["characters"],
        "score_components": best["score_components"],
        "evaluated_sets": evaluated_sets,
        "tie_break": "total_objective_desc,semantic_desc,sorted_record_ids_asc",
    }
