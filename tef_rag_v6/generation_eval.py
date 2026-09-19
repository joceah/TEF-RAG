"""Frozen TEF-RAG v6 structured-generation schema validation and evaluation.

This module is deliberately retrieval-method agnostic. It scores only a generated
work order/action plan against generation gold under protocol v1.2.
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from itertools import combinations, permutations
import json
import math
import re
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator


SCALAR_SLOTS = (
    ("asset_id",),
    ("diagnosis", "status"),
    ("diagnosis", "concept"),
    ("applicable_procedure", "status"),
    ("applicable_procedure", "procedure_version"),
    ("verification_or_uncertainty", "status"),
    ("verification_or_uncertainty", "statement"),
)


def _path(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _compact_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\s\u3000]+", " ", value).strip()
    value = re.sub(r"[，、；：。！？,.!?;:]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


class Canonicalizer:
    def __init__(self, alias_registry: dict[str, Any], parameter_registry: dict[str, Any]):
        self.status_alias: dict[str, str] = {}
        for canonical, aliases in alias_registry.get("status_aliases", {}).items():
            for alias in [canonical, *aliases]:
                self.status_alias[_compact_text(str(alias))] = canonical
        self.action_alias: dict[str, str] = {}
        for canonical, aliases in alias_registry.get("action_type_aliases", {}).items():
            for alias in [canonical, *aliases]:
                self.action_alias[_compact_text(str(alias))] = canonical
        self.parameter_alias: dict[str, str] = {}
        for canonical, aliases in parameter_registry.get("aliases", {}).items():
            for alias in [canonical, *aliases]:
                self.parameter_alias[_compact_text(str(alias))] = canonical
        self.numeric_tolerance = float(parameter_registry.get("numeric_tolerance", 1e-6))

    def text(self, value: Any) -> Any:
        if value is None:
            return None
        return _compact_text(value) if isinstance(value, str) else value

    def status(self, value: Any) -> Any:
        if value is None:
            return None
        text = self.text(value)
        return self.status_alias.get(text, text)

    def action_type(self, value: Any) -> Any:
        if value is None:
            return None
        text = self.text(value)
        return self.action_alias.get(text, text)

    def parameter_key(self, value: Any) -> Any:
        text = self.text(value)
        return self.parameter_alias.get(text, text)

    def parameter_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {self.parameter_key(k): self.parameter_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
        if isinstance(value, list):
            return [self.parameter_value(v) for v in value]
        return self.text(value) if isinstance(value, str) else value

    def _si(self, value: Any, unit: Any) -> tuple[Any, Any]:
        units = {
            "v": ("v", "1"), "mv": ("v", "0.001"), "kv": ("v", "1000"),
            "a": ("a", "1"), "ma": ("a", "0.001"),
            "ω": ("ohm", "1"), "ohm": ("ohm", "1"), "kω": ("ohm", "1000"), "kohm": ("ohm", "1000"),
            "pa": ("pa", "1"), "kpa": ("pa", "1000"), "mpa": ("pa", "1000000"),
            "s": ("s", "1"), "ms": ("s", "0.001"), "min": ("s", "60"), "h": ("s", "3600"),
            "k": ("k", "1"), "°c": ("k", "1"), "℃": ("k", "1"),
        }
        key = self.text(unit) if unit is not None else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or key not in units:
            return value, key
        target, factor = units[key]
        result = Decimal(str(value)) * Decimal(factor)
        if key in ("°c", "℃"):
            result += Decimal("273.15")
        return result, target

    def _parameter_entry_equal(self, left: Any, right: Any) -> bool:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return self.text(left) == self.text(right) if isinstance(left, str) and isinstance(right, str) else left == right
        if set(left) != {"value", "unit"} or set(right) != {"value", "unit"}:
            return False
        lv, lu = left["value"], left["unit"]
        rv, ru = right["value"], right["unit"]
        if isinstance(lv, dict) or isinstance(rv, dict):
            if not isinstance(lv, dict) or not isinstance(rv, dict) or set(lv) != {"lower", "upper"} or set(rv) != {"lower", "upper"}:
                return False
            return all(self._parameter_entry_equal({"value": lv[k], "unit": lu}, {"value": rv[k], "unit": ru}) for k in ("lower", "upper"))
        lv, lu = self._si(lv, lu)
        rv, ru = self._si(rv, ru)
        if lu != ru:
            return False
        if isinstance(lv, (int, float, Decimal)) and not isinstance(lv, bool) and isinstance(rv, (int, float, Decimal)) and not isinstance(rv, bool):
            return abs(Decimal(str(lv)) - Decimal(str(rv))) <= Decimal(str(self.numeric_tolerance))
        return self.text(lv) == self.text(rv) if isinstance(lv, str) and isinstance(rv, str) else lv == rv

    def parameters_equal(self, left: Any, right: Any) -> bool:
        if isinstance(left, dict) and isinstance(right, dict):
            l = {self.parameter_key(k): v for k, v in left.items()}
            r = {self.parameter_key(k): v for k, v in right.items()}
            return set(l) == set(r) and all(self._parameter_entry_equal(l[k], r[k]) for k in l)
        if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
            return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=self.numeric_tolerance)
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            l = {self.parameter_key(k): v for k, v in left.items()}
            r = {self.parameter_key(k): v for k, v in right.items()}
            return set(l) == set(r) and all(self.parameters_equal(l[k], r[k]) for k in l)
        if isinstance(left, list):
            return len(left) == len(right) and all(self.parameters_equal(a, b) for a, b in zip(left, right))
        if isinstance(left, str):
            return self.text(left) == self.text(right)
        return left == right

    def action_equal(self, pred: dict[str, Any], gold: dict[str, Any]) -> bool:
        return (
            self.action_type(pred.get("action_type")) == self.action_type(gold.get("action_type"))
            and self.text(pred.get("target")) == self.text(gold.get("target"))
            and self.parameters_equal(pred.get("parameters", {}), gold.get("parameters", {}))
        )

    def action_key(self, action: dict[str, Any]) -> str:
        value = {
            "action_type": self.action_type(action.get("action_type")),
            "target": self.text(action.get("target")),
            "parameters": self.parameter_value(action.get("parameters", {})),
        }
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def work_semantic(self, work: dict[str, Any], mapped_recommended: list[str] | None = None) -> dict[str, Any]:
        out = {
            "asset_id": self.text(work.get("asset_id")),
            "diagnosis": {
                "status": self.status(_path(work, ("diagnosis", "status"))),
                "concept": self.text(_path(work, ("diagnosis", "concept"))),
            },
            "applicable_procedure": {
                "status": self.status(_path(work, ("applicable_procedure", "status"))),
                "procedure_version": self.text(_path(work, ("applicable_procedure", "procedure_version"))),
            },
            "verification_or_uncertainty": {
                "status": self.status(_path(work, ("verification_or_uncertainty", "status"))),
                "statement": self.text(_path(work, ("verification_or_uncertainty", "statement"))),
            },
        }
        if mapped_recommended is not None:
            out["recommended_actions"] = sorted(mapped_recommended)
        return out


def _ids(actions: list[dict[str, Any]]) -> list[str]:
    return [str(a.get("action_id")) for a in actions]


def dependency_edges(actions: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(str(parent), str(action.get("action_id"))) for action in actions for parent in action.get("depends_on", [])}


def has_cycle(actions: list[dict[str, Any]]) -> bool:
    nodes = set(_ids(actions))
    graph = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, target in dependency_edges(actions):
        if source not in nodes or target not in nodes:
            return True
        graph[source].append(target)
        indegree[target] += 1
    q = deque([node for node, degree in indegree.items() if degree == 0])
    seen = 0
    while q:
        node = q.popleft()
        seen += 1
        for nxt in graph[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                q.append(nxt)
    return seen != len(nodes)


def transitive_closure(actions: list[dict[str, Any]]) -> set[tuple[str, str]]:
    nodes = set(_ids(actions))
    graph: dict[str, set[str]] = {node: set() for node in nodes}
    for source, target in dependency_edges(actions):
        graph.setdefault(source, set()).add(target)
    closure: set[tuple[str, str]] = set()
    for source in nodes:
        stack = list(graph[source])
        seen: set[str] = set()
        while stack:
            target = stack.pop()
            if target in seen:
                continue
            seen.add(target)
            closure.add((source, target))
            stack.extend(graph.get(target, set()) - seen)
    return closure


def maximum_action_matching(pred_actions: list[dict[str, Any]], gold_actions: list[dict[str, Any]], canon: Canonicalizer) -> dict[str, str]:
    gold_by_id = {str(a["action_id"]): a for a in gold_actions}
    adjacency = {
        str(pred["action_id"]): [gid for gid, gold in gold_by_id.items() if canon.action_equal(pred, gold)]
        for pred in pred_actions
    }
    match_gold: dict[str, str] = {}

    def augment(pid: str, seen: set[str]) -> bool:
        for gid in adjacency.get(pid, []):
            if gid in seen:
                continue
            seen.add(gid)
            if gid not in match_gold or augment(match_gold[gid], seen):
                match_gold[gid] = pid
                return True
        return False

    for pid in sorted(adjacency):
        augment(pid, set())
    return {pid: gid for gid, pid in match_gold.items()}


def resolve_duplicate_matching(pred: dict[str, Any], gold: dict[str, Any], canon: Canonicalizer, initial: dict[str, str]) -> dict[str, str]:
    """Choose a maximum matching using graph, recommendation and citation semantics."""
    groups: dict[str, list[str]] = {}
    for action in pred["action_plan"]:
        aid = str(action["action_id"])
        groups.setdefault(canon.action_key(action), []).append(aid)
    candidates = [initial]
    for pids in groups.values():
        sample = next(action for action in pred["action_plan"] if str(action["action_id"]) == pids[0])
        gids = [str(action["action_id"]) for action in gold["action_plan"] if canon.action_equal(sample, action)]
        if len(pids) < 2 or not gids:
            continue
        count = min(len(pids), len(gids))
        expanded = []
        for mapping in candidates:
            base = {pid: gid for pid, gid in mapping.items() if pid not in pids}
            for selected in combinations(pids, count):
                for ordered in permutations(gids, count):
                    choice = {**base, **dict(zip(selected, ordered))}
                    if len(choice) == len(initial) and len(set(choice.values())) == len(choice):
                        expanded.append(choice)
                        if len(expanded) > 50000:
                            raise RuntimeError("ambiguous duplicate-action matching exceeds deterministic limit")
        if expanded:
            candidates = expanded
    gold_closure = transitive_closure(gold["action_plan"])
    gold_links = _claim_links(gold, None, canon, prediction=False)
    gold_rec = set(map(str, gold["work_order"]["recommended_actions"]))
    pred_rec = set(map(str, pred["work_order"]["recommended_actions"]))
    def score(mapping: dict[str, str]) -> tuple[int, int, int]:
        closure, _, _ = _map_closure(pred["action_plan"], mapping)
        links = _claim_links(pred, mapping, canon, prediction=True)
        return (len(closure & gold_closure) - len(closure - gold_closure),
                len(links & gold_links) - len(links - gold_links),
                len({mapping[x] for x in pred_rec if x in mapping} & gold_rec))
    return max(candidates, key=score)


def f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    if tp == fp == fn == 0:
        return 1.0, 1.0, 1.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, score


def validate_generation_output(
    value: Any,
    schema: dict[str, Any],
    allowed_evidence_ids: set[str] | None = None,
    expected_asset_id: str | None = None,
) -> list[str]:
    errors = [f"schema:{e.message}" for e in Draft202012Validator(schema).iter_errors(value)]
    if not isinstance(value, dict):
        return errors or ["top-level object required"]
    work = value.get("work_order") if isinstance(value.get("work_order"), dict) else {}
    actions = value.get("action_plan") if isinstance(value.get("action_plan"), list) else []
    action_ids = _ids([a for a in actions if isinstance(a, dict)])
    if len(action_ids) != len(set(action_ids)):
        errors.append("duplicate action_id")
    if expected_asset_id is not None and work.get("asset_id") != expected_asset_id:
        errors.append("asset_id mismatch")
    if isinstance(work.get("recommended_actions"), list) and not set(map(str, work["recommended_actions"])).issubset(set(action_ids)):
        errors.append("recommended_actions outside action_plan")
    if has_cycle([a for a in actions if isinstance(a, dict)]):
        errors.append("dependency graph invalid/cyclic")

    citation_lists: list[list[str]] = []
    for name in ("diagnosis", "applicable_procedure", "verification_or_uncertainty"):
        obj = work.get(name)
        if isinstance(obj, dict) and isinstance(obj.get("supporting_evidence_ids"), list):
            citation_lists.append(list(map(str, obj["supporting_evidence_ids"])))
    for action in actions:
        if isinstance(action, dict) and isinstance(action.get("supporting_evidence_ids"), list):
            citation_lists.append(list(map(str, action["supporting_evidence_ids"])))
    top = list(map(str, work.get("supporting_evidence_ids", []))) if isinstance(work.get("supporting_evidence_ids"), list) else []
    union = sorted({eid for refs in citation_lists for eid in refs})
    if sorted(set(top)) != union:
        errors.append("top citation union mismatch")
    if allowed_evidence_ids is not None:
        for refs in [top, *citation_lists]:
            extra = set(refs) - allowed_evidence_ids
            if extra:
                errors.append("citation outside supplied evidence: " + ",".join(sorted(extra)))
    return sorted(set(errors))


def _map_closure(actions: list[dict[str, Any]], mapping: dict[str, str]) -> tuple[set[tuple[str, str]], bool, int]:
    closure = transitive_closure(actions)
    out: set[tuple[str, str]] = set()
    ok = True
    unmatched_edges = 0
    for source, target in closure:
        if source not in mapping or target not in mapping:
            ok = False
            unmatched_edges += 1
            continue
        out.add((mapping[source], mapping[target]))
    return out, ok, unmatched_edges


def _semantic_obj_equal(pred_obj: dict[str, Any], gold_obj: dict[str, Any], canon: Canonicalizer, fields: tuple[str, ...]) -> bool:
    for field in fields:
        p = pred_obj.get(field)
        g = gold_obj.get(field)
        if field == "status":
            if canon.status(p) != canon.status(g):
                return False
        elif canon.text(p) != canon.text(g):
            return False
    return True


def _work_claim_key(name: str, obj: dict[str, Any], canon: Canonicalizer) -> str:
    if name == "diagnosis":
        payload = (canon.status(obj.get("status")), canon.text(obj.get("concept")))
    elif name == "applicable_procedure":
        payload = (canon.status(obj.get("status")), canon.text(obj.get("procedure_version")))
    else:
        payload = (canon.status(obj.get("status")), canon.text(obj.get("statement")))
    return name + ":" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _claim_links(value: dict[str, Any], mapping: dict[str, str] | None, canon: Canonicalizer, prediction: bool) -> set[tuple[str, str]]:
    work = value["work_order"]
    links: set[tuple[str, str]] = set()
    for name in ("diagnosis", "applicable_procedure", "verification_or_uncertainty"):
        claim = _work_claim_key(name, work[name], canon)
        for eid in work[name].get("supporting_evidence_ids", []):
            links.add((claim, str(eid)))
    for action in value.get("action_plan", []):
        aid = str(action["action_id"])
        if prediction:
            key = mapping.get(aid) if mapping else None
            claim = f"action:{key}" if key else "unmatched:" + canon.action_key(action)
        else:
            claim = f"action:{aid}"
        for eid in action.get("supporting_evidence_ids", []):
            links.add((claim, str(eid)))
    return links


def _required_claim_support(gold: dict[str, Any], pred: dict[str, Any], mapping: dict[str, str], canon: Canonicalizer) -> tuple[int, int]:
    required: list[tuple[str, set[str]]] = []
    gw = gold["work_order"]
    for name in ("diagnosis", "applicable_procedure", "verification_or_uncertainty"):
        refs = set(map(str, gw[name].get("supporting_evidence_ids", [])))
        if refs:
            required.append((_work_claim_key(name, gw[name], canon), refs))
    for action in gold.get("action_plan", []):
        refs = set(map(str, action.get("supporting_evidence_ids", [])))
        if refs:
            required.append((f"action:{action['action_id']}", refs))
    pred_links = _claim_links(pred, mapping, canon, prediction=True)
    hits = sum(any((claim, eid) in pred_links for eid in allowed) for claim, allowed in required)
    return hits, len(required)


def evaluate_generation_prediction(
    pred: dict[str, Any],
    gold: dict[str, Any],
    schema: dict[str, Any],
    canon: Canonicalizer,
    allowed_evidence_ids: set[str],
    expected_asset_id: str,
) -> dict[str, float]:
    schema_errors = validate_generation_output(pred, schema, allowed_evidence_ids, expected_asset_id)
    schema_valid = float(not schema_errors)
    pred_actions = pred.get("action_plan", []) if isinstance(pred.get("action_plan"), list) else []
    gold_actions = gold.get("action_plan", []) if isinstance(gold.get("action_plan"), list) else []
    mapping = maximum_action_matching(pred_actions, gold_actions, canon)
    mapping = resolve_duplicate_matching(pred, gold, canon, mapping)
    matched = len(mapping)
    ap, ar, af = f1(matched, len(pred_actions) - matched, len(gold_actions) - matched)

    gold_closure = transitive_closure(gold_actions)
    pred_closure_mapped, all_edge_nodes_matched, unmatched_pred_edges = _map_closure(pred_actions, mapping)
    dep_tp = len(pred_closure_mapped & gold_closure)
    dp, dr, df = f1(
        dep_tp,
        len(pred_closure_mapped - gold_closure) + unmatched_pred_edges,
        len(gold_closure - pred_closure_mapped),
    )
    reverse_conflict = any((b, a) in gold_closure for a, b in pred_closure_mapped)
    order_valid = float(not has_cycle(pred_actions) and all_edge_nodes_matched and not reverse_conflict)

    mapped_rec: list[str] = []
    rec_mapping_ok = True
    for aid in pred.get("work_order", {}).get("recommended_actions", []):
        gid = mapping.get(str(aid))
        if gid is None:
            rec_mapping_ok = False
        else:
            mapped_rec.append(gid)
    gold_rec = sorted(map(str, gold.get("work_order", {}).get("recommended_actions", [])))

    pred_work_sem = canon.work_semantic(pred.get("work_order", {}), mapped_rec)
    gold_work_sem = canon.work_semantic(gold.get("work_order", {}), gold_rec)
    work_order_em = float(rec_mapping_ok and pred_work_sem == gold_work_sem)

    all_actions_exact = matched == len(pred_actions) == len(gold_actions)
    plan_em = float(
        all_actions_exact and rec_mapping_ok and sorted(mapped_rec) == gold_rec
        and all_edge_nodes_matched and pred_closure_mapped == gold_closure
    )

    slot_scores: list[float] = []
    pw = pred.get("work_order", {})
    gw = gold.get("work_order", {})
    for keys in SCALAR_SLOTS:
        pv = _path(pw, keys)
        gv = _path(gw, keys)
        if gv is None:
            if pv is not None:
                slot_scores.append(0.0)
            continue
        if keys[-1] == "status":
            slot_scores.append(float(canon.status(pv) == canon.status(gv)))
        else:
            slot_scores.append(float(canon.text(pv) == canon.text(gv)))
    field_macro_f1 = sum(slot_scores) / len(slot_scores) if slot_scores else 1.0

    pred_links = _claim_links(pred, mapping, canon, prediction=True)
    gold_links = _claim_links(gold, None, canon, prediction=False)
    cit_tp = len(pred_links & gold_links)
    cp, cr, cf = f1(cit_tp, len(pred_links - gold_links), len(gold_links - pred_links))
    support_hits, support_total = _required_claim_support(gold, pred, mapping, canon)
    support_recall = support_hits / support_total if support_total else 1.0

    illegal_citation = any("citation" in error for error in schema_errors)
    end_to_end_em = float(work_order_em and plan_em and schema_valid and not illegal_citation)
    diagnosis_ok = _semantic_obj_equal(pw.get("diagnosis", {}), gw.get("diagnosis", {}), canon, ("status", "concept"))
    verification_ok = _semantic_obj_equal(
        pw.get("verification_or_uncertainty", {}),
        gw.get("verification_or_uncertainty", {}),
        canon,
        ("status", "statement"),
    )
    task_success = float(
        schema_valid and diagnosis_ok and verification_ok and all_actions_exact
        and pred_closure_mapped == gold_closure and order_valid and support_hits == support_total
    )

    return {
        "schema_validity": schema_valid,
        "field_macro_f1_strict": field_macro_f1,
        "work_order_em_strict": work_order_em,
        "action_precision": ap,
        "action_recall": ar,
        "action_f1": af,
        "dependency_precision": dp,
        "dependency_recall": dr,
        "dependency_f1": df,
        "order_validity": order_valid,
        "plan_em_strict": plan_em,
        "citation_precision": cp,
        "citation_recall": cr,
        "citation_f1": cf,
        "evidence_support_recall": support_recall,
        "end_to_end_em_strict": end_to_end_em,
        "task_success": task_success,
    }


def macro_average(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {key: sum(row[key] for row in rows) / len(rows) for key in keys}
