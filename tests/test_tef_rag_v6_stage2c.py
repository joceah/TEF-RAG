import inspect
import subprocess
import sys
from pathlib import Path

from scripts.run_tef_rag_v6_stage2c import (
    assignment_satisfies, feasible_assignments, funnel_flags, matrix_category, objective_category,
    official_predicate,
)
from tef_rag_v6 import TEFRAGV6


GOLD = {"required_groups": [
    {"group_id": "G1", "acceptable_evidence_ids": ["A", "B"]},
    {"group_id": "G2", "acceptable_evidence_ids": ["C"]},
    {"group_id": "G3", "acceptable_evidence_ids": ["D"]}],
    "required_flow_edges": [
        {"from_group": "G1", "to_group": "G2", "relation_type": "supports",
         "allowed_endpoint_pairs": [["A", "C"]]},
        {"from_group": "G1", "to_group": "G3", "relation_type": "verifies",
         "allowed_endpoint_pairs": [["B", "D"]]}]}


def test_matrix_four_cases():
    assert matrix_category(True, True).startswith("A_")
    assert matrix_category(True, False).startswith("B_")
    assert matrix_category(False, True).startswith("C_")
    assert matrix_category(False, False).startswith("D_")


def test_global_consistency_prevents_edgewise_mixing():
    assert not feasible_assignments({"A", "B", "C", "D"}, GOLD, official_predicate)


def test_funnel_levels_are_distinct():
    gold = {"required_groups": [
        {"group_id": "X", "acceptable_evidence_ids": ["A"]},
        {"group_id": "Y", "acceptable_evidence_ids": ["B"]}],
        "required_flow_edges": [{"from_group": "X", "to_group": "Y",
                                 "relation_type": "verifies", "allowed_endpoint_pairs": [["A", "B"]]}]}
    official, prefilter, edge, typed = funnel_flags({"A", "B"}, gold, set(), set(), set())
    assert official and not prefilter and not edge and not typed
    _, prefilter, edge, typed = funnel_flags({"A", "B"}, gold, {("A", "B")}, set(), set())
    assert prefilter and not edge and not typed
    _, _, edge, typed = funnel_flags({"A", "B"}, gold, {("A", "B")}, {("A", "B")},
                                     {("A", "B", "supports")})
    assert edge and not typed
    _, _, _, typed = funnel_flags({"A", "B"}, gold, {("A", "B")}, {("A", "B")},
                                  {("A", "B", "verifies")})
    assert typed


def test_objective_vs_search_failure_classification():
    assert objective_category(5.0, 4.0) == "objective_misalignment"
    assert objective_category(4.0, 5.0) == "search_failure_under_current_objective"
    assert objective_category(4.0, 4.0) == "other_ambiguous"


def test_diagnostics_are_isolated_and_test_split_unavailable():
    for method in (TEFRAGV6.retrieve, TEFRAGV6._select_flow, TEFRAGV6._select_flow_beam):
        assert "gold" not in inspect.signature(method).parameters
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, str(root / "scripts/run_tef_rag_v6_stage2c.py"),
                              "--split", "test"], cwd=root, capture_output=True, text=True)
    assert process.returncode != 0 and "invalid choice" in process.stderr
