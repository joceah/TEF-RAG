"""Deterministic v1.1 canonicalization for existing TEF-RAG generation gold.

This script never calls an API. It reads only public query/chain/evidence and
the locally saved generation annotation artifacts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "experiments/runs/tef_v6_generation_gold_v1"
OUT = ROOT / "data/generated/tef_v6_generation_gold_v1"
PRIVATE = Path(os.environ.get("TEF_GENERATION_PRIVATE_ROOT", str(ROOT.parent / ".tef_v6_generation_gold_private")))
ADDENDUM = ROOT / "plans/TEF_RAG_v6_generation_evaluation_protocol_v1_1_addendum.md"
sys.path.insert(0, str(ROOT / "scripts"))
import generate_tef_v6_generation_gold_v1 as base  # noqa: E402


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def parse_time(value: Any):
    return base.parse_time(value) if value else None


def procedure_rows(case: dict[str, Any], intent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [
        row for row in intent["visible_evidence"]
        if row.get("event_type") == "procedure_applicability"
        or row.get("source_type") == "procedure"
        or row.get("procedure_version") is not None
    ]
    cutoff = parse_time(intent["shared_cutoff"])
    model = case["chain"].get("asset_model")
    valid: list[dict[str, Any]] = []
    for row in rows:
        scope = row.get("model_scope") or []
        vf = parse_time(row.get("valid_from"))
        vt = parse_time(row.get("valid_to"))
        withdrawn = parse_time(row.get("withdrawn_at"))
        if scope and model not in scope:
            continue
        if vf is not None and cutoff < vf:
            continue
        if vt is not None and cutoff >= vt:
            continue
        if withdrawn is not None and cutoff >= withdrawn:
            continue
        valid.append(row)
    return rows, valid


def procedure_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(sorted(row.get("model_scope") or ([row.get("asset_model")] if row.get("asset_model") else []))),
        tuple(sorted(row.get("source_basis_ids") or [])),
        row.get("source_type") or "procedure",
    )


def canonicalize_procedure(proc: dict[str, Any], case: dict[str, Any], intent: dict[str, Any]) -> None:
    rows, valid = procedure_rows(case, intent)
    by_id = {row.get("evidence_id"): row for row in rows}
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in valid:
        identity = procedure_identity(row)
        version = row.get("procedure_version")
        key = (identity, version)
        group = groups.setdefault(key, {"identity": identity, "version": version, "rows": [], "ids": []})
        group["rows"].append(row)
        if row.get("evidence_id"):
            group["ids"].append(row["evidence_id"])
    superseded_ids = {row.get("supersedes") for row in valid if row.get("supersedes")}
    current = [group for group in groups.values() if not superseded_ids.intersection(group["ids"])]
    if len(current) == 1:
        group = current[0]
        proc["status"] = "applicable"
        proc["procedure_version"] = group["version"]
        proc["supporting_evidence_ids"] = sorted(set(group["ids"]))
    elif len(current) > 1:
        proc["status"] = "uncertain"
        proc["procedure_version"] = None
        proc["supporting_evidence_ids"] = sorted({eid for group in current for eid in group["ids"]})
    elif rows and superseded_ids.intersection(by_id):
        proc["status"] = "superseded"
        old = [by_id[eid] for eid in sorted(superseded_ids.intersection(by_id))]
        proc["procedure_version"] = old[-1].get("procedure_version") if len(old) == 1 else None
        proc["supporting_evidence_ids"] = [row["evidence_id"] for row in old if row.get("evidence_id")]
    else:
        proc["status"] = "not_applicable"
        proc["procedure_version"] = None
        proc["supporting_evidence_ids"] = []


def dedupe_ids(obj: dict[str, Any]) -> None:
    refs = obj.get("supporting_evidence_ids")
    if isinstance(refs, list):
        obj["supporting_evidence_ids"] = sorted(dict.fromkeys(refs))


def canonicalize_gold(gold: dict[str, Any], case: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(gold)
    work = value["work_order"]
    canonicalize_procedure(work["applicable_procedure"], case, intent)
    for name in ("diagnosis", "verification_or_uncertainty"):
        dedupe_ids(work[name])
    for action in value.get("action_plan", []):
        if isinstance(action, dict):
            dedupe_ids(action)
    refs: set[str] = set()
    for name in ("diagnosis", "applicable_procedure", "verification_or_uncertainty"):
        refs.update(work[name].get("supporting_evidence_ids", []))
    for action in value.get("action_plan", []):
        refs.update(action.get("supporting_evidence_ids", []))
    work["supporting_evidence_ids"] = sorted(refs)
    return value


def canonicalize_wrapper(raw: Any, case: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        golds = base.unwrap_results(raw, case["intents"])
        return {"gold_by_intent": [{"intent_id": intent["intent_id"], "gold": canonicalize_gold(golds[intent["intent_id"]], case, intent)} for intent in case["intents"]]}
    except Exception:
        return None


def load_saved(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def cache_map(dirs: list[Path]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                row = read_json(path)
                key = row.get("logical_key")
                if key and key not in out:
                    out[key] = row.get("result")
            except Exception:
                continue
    return out


def candidate_adjudication(chain_id: str, saved: dict[str, Any] | None, cache: dict[str, Any]) -> Any:
    if saved and saved.get("result") is not None:
        return saved["result"]
    for key in (f"repair:adjudication:{chain_id}:equal", f"repair:adjudication:{chain_id}", f"adjudication:{chain_id}"):
        if key in cache:
            return cache[key]
    return None


def signatures(wrapper: dict[str, Any] | None, intents: list[dict[str, Any]]) -> dict[str, str] | None:
    if wrapper is None:
        return None
    try:
        golds = base.unwrap_results(wrapper, intents)
        return {intent["intent_id"]: base.canonical_signature(golds[intent["intent_id"]]) for intent in intents}
    except Exception:
        return None


def validate_wrapper(wrapper: dict[str, Any] | None, case: dict[str, Any]) -> tuple[bool, dict[str, list[str]]]:
    if wrapper is None:
        return False, {"wrapper": ["missing or malformed result"]}
    try:
        golds = base.unwrap_results(wrapper, case["intents"])
    except Exception as exc:
        return False, {"wrapper": [str(exc)]}
    errors = {intent["intent_id"]: base.validate_gold(golds[intent["intent_id"]], intent, case["chain"]) for intent in case["intents"]}
    return not any(errors.values()), errors


def fields_from(a: dict[str, Any] | None, b: dict[str, Any] | None, intents: list[dict[str, Any]]) -> dict[str, list[str]]:
    if not a or not b:
        return {intent["intent_id"]: ["wrapper_validation"] for intent in intents}
    try:
        ga, gb = base.unwrap_results(a, intents), base.unwrap_results(b, intents)
    except Exception:
        return {intent["intent_id"]: ["wrapper_validation"] for intent in intents}
    out: dict[str, list[str]] = {}
    for intent in intents:
        iid = intent["intent_id"]
        if iid not in ga or iid not in gb:
            out[iid] = ["wrapper_validation"]
            continue
        left, right = ga[iid], gb[iid]
        fields = []
        for field in ("diagnosis", "applicable_procedure", "verification_or_uncertainty", "recommended_actions", "supporting_evidence_ids"):
            if json.dumps(left["work_order"].get(field), ensure_ascii=False, sort_keys=True) != json.dumps(right["work_order"].get(field), ensure_ascii=False, sort_keys=True):
                fields.append(f"work_order.{field}")
        if json.dumps(left.get("action_plan"), ensure_ascii=False, sort_keys=True) != json.dumps(right.get("action_plan"), ensure_ascii=False, sort_keys=True):
            fields.append("action_plan")
        out[iid] = fields
    return out


def main() -> None:
    cases_by_split = {split: base.build_cases(split) for split in base.SPLITS}
    public_cache = cache_map([RUN / "api_retry_cache", RUN / "api_cache"])
    private_cache = cache_map([PRIVATE / "api_retry_cache", PRIVATE / "api_cache"])
    qa: dict[str, Any] = {"canonicalization_version": "v1.1", "splits": {}, "all_checks_pass": True}
    disagreement: dict[str, Any] = {}
    counts: dict[str, int] = {}
    public_hashes: dict[str, str] = {}
    private_hash = None
    repair_counts = {"top_citation_union": 0, "procedure_canonicalization": 0, "object_citation_dedupe": 0}
    audit_public: list[dict[str, Any]] = []
    audit_test = {"chains": 0, "accepted_chains": 0, "review_unresolved_chains": 0, "semantic_gold_objects": 0}
    for split, cases in cases_by_split.items():
        cache = private_cache if split == "test" else public_cache
        finals_dir = (PRIVATE / "adjudication") if split == "test" else (RUN / "adjudication")
        pass_a_dir = (PRIVATE / "pass_a") if split == "test" else (RUN / "pass_a")
        pass_b_dir = (PRIVATE / "pass_b") if split == "test" else (RUN / "pass_b")
        rows: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        split_qa = {"semantic_gold_objects": 0, "schema_valid": 0, "temporal_valid": 0, "procedure_valid": 0, "citation_valid": 0, "provenance_valid": 0, "dag_valid": 0, "paraphrase_consistent": 0, "review_unresolved": 0}
        statuses: Counter[str] = Counter()
        for case in cases:
            cid = case["chain"]["chain_id"]
            a_saved = load_saved(pass_a_dir / f"{cid}.json")
            b_saved = load_saved(pass_b_dir / f"{cid}.json")
            final_saved = load_saved(finals_dir / f"{cid}.json")
            a = canonicalize_wrapper((a_saved or {}).get("result"), case)
            b = canonicalize_wrapper((b_saved or {}).get("result"), case)
            sa = signatures(a, case["intents"])
            sb = signatures(b, case["intents"])
            chosen: dict[str, Any] | None = None
            raw_source: Any = None
            local_repairs = {"top_citation_union": 0, "procedure_canonicalization": 0, "object_citation_dedupe": 0}
            status = "REVIEW_UNRESOLVED"
            used_adjudication = False
            if a is not None and b is not None and sa == sb:
                ok, _ = validate_wrapper(a, case)
                if ok:
                    chosen, status, raw_source = a, "accepted_agreement", (a_saved or {}).get("result")
                else:
                    raw_source = candidate_adjudication(cid, final_saved, cache)
                    adj = canonicalize_wrapper(raw_source, case)
                    ok, _ = validate_wrapper(adj, case)
                    if ok:
                        chosen, status, used_adjudication = adj, "adjudicated", True
            else:
                raw_source = candidate_adjudication(cid, final_saved, cache)
                adj = canonicalize_wrapper(raw_source, case)
                ok, _ = validate_wrapper(adj, case)
                if ok:
                    chosen, status, used_adjudication = adj, "adjudicated", True
            statuses[status] += 1
            if split != "test":
                disagreement[cid] = {"chain_id": cid, "split": split, "status": status, "used_adjudication": used_adjudication, "disagreement_fields": fields_from(a, b, case["intents"]), "pass_a_pass_b_canonical_equal": bool(sa is not None and sa == sb)}
            if chosen is None:
                split_qa["review_unresolved"] += len(case["intents"])
                if split != "test":
                    audit_public.append({"chain_id": cid, "split": split, "status": status, "used_adjudication": used_adjudication, "pass_a_pass_b_canonical_equal": bool(sa is not None and sa == sb), "semantic_gold_objects": 0, "repairs": local_repairs})
                else:
                    audit_test["chains"] += 1
                    audit_test["review_unresolved_chains"] += 1
                continue
            golds = base.unwrap_results(chosen, case["intents"])
            raw_golds = None
            if raw_source is not None:
                try:
                    raw_golds = base.unwrap_results(raw_source, case["intents"])
                except Exception:
                    raw_golds = None
            for intent in case["intents"]:
                gold = golds[intent["intent_id"]]
                if raw_golds and intent["intent_id"] in raw_golds:
                    before = raw_golds[intent["intent_id"]]
                    if before["work_order"].get("supporting_evidence_ids") != gold["work_order"].get("supporting_evidence_ids"):
                        repair_counts["top_citation_union"] += 1
                        local_repairs["top_citation_union"] += 1
                    if before["work_order"].get("applicable_procedure") != gold["work_order"].get("applicable_procedure"):
                        repair_counts["procedure_canonicalization"] += 1
                        local_repairs["procedure_canonicalization"] += 1
                    for name in ("diagnosis", "verification_or_uncertainty"):
                        if before["work_order"][name].get("supporting_evidence_ids") != gold["work_order"][name].get("supporting_evidence_ids"):
                            repair_counts["object_citation_dedupe"] += 1
                            local_repairs["object_citation_dedupe"] += 1
                    for before_action, after_action in zip(before.get("action_plan", []), gold.get("action_plan", [])):
                        if before_action.get("supporting_evidence_ids") != after_action.get("supporting_evidence_ids"):
                            repair_counts["object_citation_dedupe"] += 1
                            local_repairs["object_citation_dedupe"] += 1
                errors = base.validate_gold(gold, intent, case["chain"])
                split_qa["semantic_gold_objects"] += 1
                if errors:
                    split_qa["review_unresolved"] += 1
                    continue
                for field in ("schema_valid", "temporal_valid", "procedure_valid", "citation_valid", "provenance_valid", "dag_valid", "paraphrase_consistent"):
                    split_qa[field] += 1
                semantic_id = f"{cid}::{intent['intent_id']}"
                rows.append(gold)
                index_rows.append({"semantic_gold_id": semantic_id, "chain_id": cid, "intent_id": intent["intent_id"], "query_ids": [q["query_id"] for q in intent["queries"]], "split": split, "query_times": [q["query_time"] for q in intent["queries"]], "visible_evidence_count": len(intent["visible_evidence_ids"])})
            if split != "test":
                audit_public.append({"chain_id": cid, "split": split, "status": status, "used_adjudication": used_adjudication, "pass_a_pass_b_canonical_equal": bool(sa is not None and sa == sb), "semantic_gold_objects": 3 if chosen is not None else 0, "repairs": local_repairs})
            else:
                audit_test["chains"] += 1
                audit_test["accepted_chains"] += 1 if chosen is not None else 0
                audit_test["review_unresolved_chains"] += 1 if chosen is None else 0
                audit_test["semantic_gold_objects"] += 3 if chosen is not None else 0
        target = OUT / "public" if split != "test" else PRIVATE
        write_jsonl(target / f"gold_{split}.jsonl", rows)
        write_jsonl(target / f"gold_{split}_index.jsonl", index_rows)
        counts[split] = len(rows)
        qa["splits"][split] = split_qa
        if split != "test":
            public_hashes[str((target / f"gold_{split}.jsonl").relative_to(ROOT))] = sha(target / f"gold_{split}.jsonl")
            public_hashes[str((target / f"gold_{split}_index.jsonl").relative_to(ROOT))] = sha(target / f"gold_{split}_index.jsonl")
        else:
            private_hash = sha(target / f"gold_{split}.jsonl")
        disagreement[split] = {"chains": len(cases), "accepted_agreement_chains": statuses.get("accepted_agreement", 0), "adjudicated_chains": statuses.get("adjudicated", 0), "review_unresolved_chains": statuses.get("REVIEW_UNRESOLVED", 0)}
    qa["all_checks_pass"] = all(item["review_unresolved"] == 0 for item in qa["splits"].values())
    metadata = OUT / "metadata"
    write_json(metadata / "annotation_qa.json", qa)
    write_json(metadata / "disagreement_summary.json", disagreement)
    write_json(metadata / "canonicalization_audit.json", {"version": "v1.1", "public_chain_records": audit_public, "private_test_aggregate": audit_test, "contains_item_level_test_answers": False})
    write_json(metadata / "test_generation_gold_aggregate.json", {"split": "test", "chains": 80, "semantic_gold_objects": counts["test"], "private_gold_sha256": private_hash, "item_level_gold_committed": False, "canonicalization_version": "v1.1"})
    manifest = read_json(metadata / "annotation_manifest.json") if (metadata / "annotation_manifest.json").exists() else {}
    manifest.update({"protocol_version": "v1.1-addendum", "canonicalization_addendum": str(ADDENDUM.relative_to(ROOT)), "canonicalization_addendum_sha256": sha(ADDENDUM), "canonicalization_audit": "data/generated/tef_v6_generation_gold_v1/metadata/canonicalization_audit.json", "deterministic_repairs": repair_counts, "semantic_gold_counts": counts, "public_hashes": public_hashes, "private_test_gold_sha256": private_hash, "review_unresolved": sum(item["review_unresolved_chains"] for key, item in disagreement.items() if key in base.SPLITS), "generation_gold_ready": qa["all_checks_pass"], "llm_calls": 0, "generation_evaluation_run": False, "retrieval_predictions_accessed": False, "retrieval_test_metrics_accessed": False, "retrieval_sealed_evaluator_accessed": False})
    write_json(metadata / "annotation_manifest.json", manifest)
    report = ["# TEF-RAG v6 generation gold v1.1 canonicalization", "", "Deterministic canonicalization only; no LLM calls. Diagnosis, action, dependency, and object-level citation semantics were not rewritten. Top-level citations were recomputed as the object-level union and procedure fields were normalized from visible procedure metadata.", "", f"- Addendum SHA256: `{sha(ADDENDUM)}`", f"- Deterministic repairs: `{json.dumps(repair_counts, ensure_ascii=False)}`", f"- Semantic objects: development={counts['development']}, validation={counts['validation']}, test={counts['test']} (test private)", f"- Remaining REVIEW_UNRESOLVED chains: {manifest['review_unresolved']}", f"- GENERATION_GOLD_READY: {manifest['generation_gold_ready']}", "", "```json", json.dumps(qa, ensure_ascii=False, indent=2), "```", ""]
    (ROOT / "markdowns/tef_rag_v6_generation_gold_v1.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({"status": "canonicalized", "counts": counts, "qa": qa, "review_unresolved": manifest["review_unresolved"], "llm_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
