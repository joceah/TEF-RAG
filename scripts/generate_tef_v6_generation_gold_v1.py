"""Generate TEF-RAG v6 generation gold from public query/chain/evidence only.

This runner is deliberately chain-level and sequential.  It never reads retrieval
gold, method predictions, sealed evaluators, or results/v6/sealed_test.  Test
generation gold is written below a private root outside this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/public"
OUT = ROOT / "data/generated/tef_v6_generation_gold_v1"
RUN = ROOT / "experiments/runs/tef_v6_generation_gold_v1"
PRIVATE = Path(os.environ.get("TEF_GENERATION_PRIVATE_ROOT", str(ROOT.parent / ".tef_v6_generation_gold_private")))
PROTOCOL = ROOT / "plans/TEF_RAG_v6_generation_evaluation_protocol_v1.md"
SEAL_COMMIT = "4cd74c51bf874beac3c72df7fa64ae89f73438b8"
MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
TEMPERATURE = 0
MAX_TOKENS = 10000
CALL_INTERVAL_SECONDS = 3.5
SPLITS = ("development", "validation", "test")
ACTION_TYPES = {"inspect", "diagnose", "isolate", "adjust", "repair", "replace", "verify", "monitor", "document", "other"}
DIAG_STATUSES = {"confirmed", "provisional", "persistent_uncertainty", "not_available"}
PROC_STATUSES = {"applicable", "superseded", "uncertain", "not_applicable"}
VERIF_STATUSES = {"verified", "pending", "persistent_uncertainty", "not_available"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def read_env() -> dict[str, str]:
    candidates = [ROOT / "local.env", ROOT.parent / "local.env", Path(r"D:\electric-project\local.env")]
    for path in candidates:
        if not path.exists():
            continue
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        if values.get("API_KEY"):
            return values
    raise RuntimeError("local.env with API_KEY not found")


def visible_evidence(query: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = parse_time(query["query_time"])
    rows: list[dict[str, Any]] = []
    for item in evidence:
        if item.get("split") != query["split"] or item.get("chain_id") != query["chain_id"]:
            continue
        if item.get("asset_id") != query.get("asset_id"):
            continue
        if parse_time(item["event_time"]) > cutoff or parse_time(item["available_at"]) > cutoff:
            continue
        is_proc = item.get("event_type") == "procedure_applicability" or item.get("source_type") == "procedure"
        if is_proc:
            if item.get("valid_from") and cutoff < parse_time(item["valid_from"]):
                continue
            if item.get("valid_to") and cutoff >= parse_time(item["valid_to"]):
                continue
            if item.get("withdrawn_at") and cutoff >= parse_time(item["withdrawn_at"]):
                continue
            scope = item.get("model_scope") or []
            scope = [scope] if isinstance(scope, str) else scope
            if scope and query.get("asset_model") not in scope:
                continue
        rows.append(item)
    return sorted(rows, key=lambda row: (row["event_time"], row["available_at"], row["evidence_id"]))


def build_cases(split: str) -> list[dict[str, Any]]:
    chains = {row["chain_id"]: row for row in read_jsonl(PUBLIC / f"chains_{split}.jsonl")}
    queries = [row for row in read_jsonl(PUBLIC / f"queries_{split}.jsonl") if row.get("split") == split]
    evidence = read_jsonl(PUBLIC / "evidence.jsonl")
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in queries:
        by_chain[query["chain_id"]].append(query)
    cases: list[dict[str, Any]] = []
    for chain_id in sorted(chains):
        chain_queries = by_chain.get(chain_id, [])
        by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for query in chain_queries:
            by_intent[query["intent_id"]].append(query)
        if len(by_intent) != 3 or any(len(items) != 2 for items in by_intent.values()):
            raise RuntimeError(f"{split}/{chain_id}: expected 3 intents x 2 paraphrases")
        intents = []
        for intent_id in sorted(by_intent):
            pair = sorted(by_intent[intent_id], key=lambda row: (row.get("paraphrase_id", 0), row["query_id"]))
            if pair[0]["query_time"] != pair[1]["query_time"]:
                # A shared semantic gold must be valid for both paraphrases.
                times = [parse_time(row["query_time"]) for row in pair]
                cutoff = min(times)
            else:
                cutoff = parse_time(pair[0]["query_time"])
            visible_by_query = [visible_evidence(row, evidence) for row in pair]
            common_ids = set(row["evidence_id"] for row in visible_by_query[0])
            for rows in visible_by_query[1:]:
                common_ids &= {row["evidence_id"] for row in rows}
            all_by_id = {row["evidence_id"]: row for row in visible_by_query[0] + visible_by_query[1]}
            common = sorted((all_by_id[eid] for eid in common_ids), key=lambda row: (row["event_time"], row["available_at"], row["evidence_id"]))
            intents.append({
                "intent_id": intent_id,
                "queries": [
                    {key: query[key] for key in ("query_id", "query_text", "query_time", "intent_id", "paraphrase_id", "asset_id", "asset_model", "chain_id")}
                    for query in pair
                ],
                "shared_cutoff": cutoff.isoformat(),
                "visible_evidence": common,
                "visible_evidence_ids": [row["evidence_id"] for row in common],
                "visibility_pair_equal": len(visible_by_query[0]) == len(visible_by_query[1]) and set(row["evidence_id"] for row in visible_by_query[0]) == set(row["evidence_id"] for row in visible_by_query[1]),
            })
        cases.append({"split": split, "chain": chains[chain_id], "intents": intents})
    return cases


def protocol_excerpt() -> str:
    return """Frozen generation protocol rules:
- Return one semantic gold per intent; both paraphrases share it.
- Inner gold object has exactly work_order and action_plan.
- work_order has asset_id, diagnosis(status/concept/supporting_evidence_ids), recommended_actions, applicable_procedure(status/procedure_version/supporting_evidence_ids), verification_or_uncertainty(status/statement/supporting_evidence_ids), and top-level supporting_evidence_ids.
- diagnosis.status must be exactly confirmed, provisional, persistent_uncertainty, or not_available. applicable_procedure.status must be exactly applicable, superseded, uncertain, or not_applicable (never use available). verification_or_uncertainty.status must be exactly verified, pending, persistent_uncertainty, or not_available.
- action_plan actions have exactly action_id, action_type (inspect/diagnose/isolate/adjust/repair/replace/verify/monitor/document/other), target, parameters, depends_on, and supporting_evidence_ids. The key is exactly `parameters`, never `explicit_parameters` or another alias.
- recommended_actions is a subset of action_plan IDs; it contains task-required treatment/maintenance actions, while support steps remain only in action_plan unless the query requires them.
- depends_on is a direct prerequisite DAG, not chronological order; do not add edges merely because event_time is earlier.
- Use only supplied evidence visible at the query cutoff (event_time and available_at); never use common sense to add diagnosis, action, target, parameter, unit, or procedure.
- Every non-null claim/action must cite directly supporting evidence IDs. If evidence is insufficient, use not_available/pending/persistent_uncertainty or omit the action.
- Output JSON only; no markdown, no explanations, no prediction-derived information.
"""


def build_prompt(case: dict[str, Any], pass_name: str) -> tuple[str, str]:
    system = "You are an independent evidence-grounded annotation specialist. " + protocol_excerpt()
    payload = {
        "pass": pass_name,
        "chain": case["chain"],
        "intents": case["intents"],
        "required_output": {"gold_by_intent": [{"intent_id": "...", "gold": {"work_order": "...", "action_plan": []}}]},
    }
    user = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return system, user


class DeepSeekClient:
    def __init__(self, cache_dir: Path):
        env = read_env()
        self.key = env["API_KEY"]
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_call = 0.0
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def call(self, system: str, user: str, logical_key: str) -> dict[str, Any]:
        payload = {
            "model": MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        request_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{request_hash}.json"
        if path.exists():
            self.stats["cache_hits"] += 1
            return read_json(path)["result"]
        wait = CALL_INTERVAL_SECONDS - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = BASE_URL.rstrip("/") + "/chat/completions"
        for attempt in range(3):
            self.last_call = time.monotonic()
            self.stats["requests"] += 1
            try:
                req = urllib.request.Request(endpoint, data=raw, headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
                with urllib.request.urlopen(req, timeout=240) as response:
                    data = json.load(response)
                content = data["choices"][0]["message"].get("content", "")
                content = content.strip().lstrip("\ufeff")
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I).strip()
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    start = content.find("{")
                    if start < 0:
                        raise
                    result, _ = json.JSONDecoder().raw_decode(content[start:])
                if not isinstance(result, dict):
                    raise ValueError("JSON object required")
                usage = data.get("usage") or {}
                self.stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                self.stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                self.stats["total_tokens"] += int(usage.get("total_tokens") or 0)
                write_json(path, {"request_hash": request_hash, "logical_key": logical_key, "model": MODEL, "temperature": TEMPERATURE, "usage": usage, "result": result})
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 402, 403):
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek HTTP {exc.code}; fail closed") from None
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError("DeepSeek network failure") from None
            except (ValueError, KeyError, IndexError, TypeError):
                if attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError("DeepSeek response JSON failure") from None
            self.stats["retries"] += 1
            time.sleep(CALL_INTERVAL_SECONDS * (attempt + 1))
        raise RuntimeError("unreachable")


def normalize_text(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    return " ".join(value.replace("\u3000", " ").split()).strip().casefold()


def canonical_signature(gold: dict[str, Any]) -> str:
    work = gold["work_order"]
    actions = gold["action_plan"]
    by_id = {item["action_id"]: item for item in actions}
    def params(item: dict[str, Any]) -> str:
        return json.dumps(item.get("parameters", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (item.get("action_type"), normalize_text(item.get("target")), params(item))
    ordered = sorted(actions, key=key)
    key_for_id = {item["action_id"]: key(item) for item in ordered}
    edges = sorted((key_for_id[parent], key_for_id[item["action_id"]]) for item in ordered for parent in item.get("depends_on", []))
    recommended = sorted(key_for_id[item] for item in work.get("recommended_actions", []))
    semantic = {
        "work_order": {
            "asset_id": work["asset_id"],
            "diagnosis": {"status": work["diagnosis"]["status"], "concept": normalize_text(work["diagnosis"].get("concept"))},
            "recommended_actions": recommended,
            "applicable_procedure": {"status": work["applicable_procedure"]["status"], "procedure_version": work["applicable_procedure"].get("procedure_version")},
            "verification_or_uncertainty": {"status": work["verification_or_uncertainty"]["status"], "statement": normalize_text(work["verification_or_uncertainty"].get("statement"))},
            "supporting_evidence_ids": sorted(work.get("supporting_evidence_ids", [])),
            "diagnosis_evidence": sorted(work["diagnosis"].get("supporting_evidence_ids", [])),
            "procedure_evidence": sorted(work["applicable_procedure"].get("supporting_evidence_ids", [])),
            "verification_evidence": sorted(work["verification_or_uncertainty"].get("supporting_evidence_ids", [])),
        },
        "action_plan": [{"key": key(item), "depends_on": sorted(key_for_id[parent] for parent in item.get("depends_on", [])), "evidence": sorted(item.get("supporting_evidence_ids", []))} for item in ordered],
        "edges": edges,
    }
    return json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def find_cycle(actions: list[dict[str, Any]]) -> bool:
    graph = {row["action_id"]: list(row.get("depends_on", [])) for row in actions}
    state: dict[str, int] = {}
    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        if any(visit(parent) for parent in graph[node]):
            return True
        state[node] = 2
        return False
    return any(visit(node) for node in graph)


def validate_gold(gold: dict[str, Any], intent: dict[str, Any], chain: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    visible = set(intent["visible_evidence_ids"])
    if set(gold) != {"work_order", "action_plan"}:
        errors.append("top-level keys")
        return errors
    work = gold.get("work_order")
    plan = gold.get("action_plan")
    if not isinstance(work, dict) or not isinstance(plan, list):
        return ["work_order/action_plan types"]
    required_work = {"asset_id", "diagnosis", "recommended_actions", "applicable_procedure", "verification_or_uncertainty", "supporting_evidence_ids"}
    if set(work) != required_work:
        errors.append("work_order keys")
    if work.get("asset_id") != chain.get("asset_id"):
        errors.append("asset consistency")
    nested_specs = [("diagnosis", {"status", "concept", "supporting_evidence_ids"}), ("applicable_procedure", {"status", "procedure_version", "supporting_evidence_ids"}), ("verification_or_uncertainty", {"status", "statement", "supporting_evidence_ids"})]
    for name, keys in nested_specs:
        obj = work.get(name)
        if not isinstance(obj, dict) or set(obj) != keys:
            errors.append(f"{name} keys")
    if isinstance(work.get("diagnosis"), dict):
        d = work["diagnosis"]
        if d.get("status") not in DIAG_STATUSES or (d.get("status") == "not_available" and (d.get("concept") is not None or d.get("supporting_evidence_ids"))):
            errors.append("diagnosis status/value")
    if isinstance(work.get("applicable_procedure"), dict):
        p = work["applicable_procedure"]
        if p.get("status") not in PROC_STATUSES or (p.get("status") == "not_applicable" and (p.get("procedure_version") is not None or p.get("supporting_evidence_ids"))):
            errors.append("procedure status/value")
    if isinstance(work.get("verification_or_uncertainty"), dict):
        v = work["verification_or_uncertainty"]
        if v.get("status") not in VERIF_STATUSES or (v.get("status") == "not_available" and (v.get("statement") is not None or v.get("supporting_evidence_ids"))):
            errors.append("verification status/value")
    if not isinstance(work.get("recommended_actions"), list) or len(work.get("recommended_actions", [])) != len(set(work.get("recommended_actions", []))):
        errors.append("recommended_actions list")
    if not isinstance(work.get("supporting_evidence_ids"), list):
        errors.append("top citations type")
    action_ids: list[str] = []
    for index, item in enumerate(plan):
        if not isinstance(item, dict) or set(item) != {"action_id", "action_type", "target", "parameters", "depends_on", "supporting_evidence_ids"}:
            errors.append(f"action {index} keys")
            continue
        action_ids.append(item.get("action_id"))
        if not isinstance(item.get("action_id"), str) or not item["action_id"]:
            errors.append(f"action {index} id")
        if item.get("action_type") not in ACTION_TYPES:
            errors.append(f"action {index} type")
        if item.get("target") is not None and not isinstance(item.get("target"), str):
            errors.append(f"action {index} target")
        if not isinstance(item.get("parameters"), dict) or not isinstance(item.get("depends_on"), list) or not isinstance(item.get("supporting_evidence_ids"), list):
            errors.append(f"action {index} fields")
    if len(action_ids) != len(set(action_ids)):
        errors.append("duplicate action IDs")
    plan_ids = set(action_ids)
    if not isinstance(work.get("recommended_actions"), list) or not set(work.get("recommended_actions", [])) <= plan_ids:
        errors.append("recommended_actions not subset of action_plan")
    for item in plan:
        if not isinstance(item, dict):
            continue
        if any(parent not in plan_ids or parent == item.get("action_id") for parent in item.get("depends_on", [])):
            errors.append(f"action {item.get('action_id')} dependency reference")
    if all(isinstance(item, dict) and "action_id" in item for item in plan) and find_cycle(plan):
        errors.append("dependency cycle")
    nested_citations = []
    if isinstance(work.get("diagnosis"), dict): nested_citations.append(work["diagnosis"].get("supporting_evidence_ids", []))
    if isinstance(work.get("applicable_procedure"), dict): nested_citations.append(work["applicable_procedure"].get("supporting_evidence_ids", []))
    if isinstance(work.get("verification_or_uncertainty"), dict): nested_citations.append(work["verification_or_uncertainty"].get("supporting_evidence_ids", []))
    nested_citations += [item.get("supporting_evidence_ids", []) for item in plan if isinstance(item, dict)]
    all_citations = set()
    for refs in nested_citations + [work.get("supporting_evidence_ids", [])]:
        if not isinstance(refs, list) or len(refs) != len(set(refs)):
            errors.append("citation list")
            continue
        all_citations.update(refs)
        if set(refs) - visible:
            errors.append("citation visibility")
    expected_union = set().union(*[set(refs) for refs in nested_citations]) if nested_citations else set()
    if set(work.get("supporting_evidence_ids", [])) != expected_union:
        errors.append("top citation union")
    if set(work.get("recommended_actions", [])) - plan_ids:
        errors.append("recommended action reference")
    return sorted(set(errors))


def unwrap_results(result: dict[str, Any], intents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    values = result.get("gold_by_intent")
    if isinstance(values, dict):
        values = [{"intent_id": key, "gold": value} for key, value in values.items()]
    if not isinstance(values, list):
        raise ValueError("gold_by_intent missing")
    out: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or "intent_id" not in item:
            raise ValueError("intent wrapper invalid")
        gold = item.get("gold", item)
        if not isinstance(gold, dict):
            raise ValueError("gold object invalid")
        out[item["intent_id"]] = gold
    expected = {intent["intent_id"] for intent in intents}
    if set(out) != expected:
        raise ValueError("intent set mismatch")
    return out


def repair_prompt(case: dict[str, Any], candidate: dict[str, Any], errors: dict[str, list[str]]) -> tuple[str, str]:
    system = "You are a strict repair annotator. " + protocol_excerpt() + " Repair only schema/provenance/protocol violations using the supplied evidence; do not add facts. Return the same gold_by_intent JSON wrapper only."
    user = json.dumps({"chain": case["chain"], "intents": case["intents"], "candidate": candidate, "validation_errors": errors}, ensure_ascii=False, separators=(",", ":"))
    return system, user


def normalize_structural_aliases(result: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply only a lossless schema-key repair after the single model repair call."""
    value = json.loads(json.dumps(result, ensure_ascii=False))
    changes: list[str] = []
    for wrapper in value.get("gold_by_intent", []) if isinstance(value, dict) and isinstance(value.get("gold_by_intent"), list) else []:
        gold = wrapper.get("gold", wrapper) if isinstance(wrapper, dict) else {}
        for action in gold.get("action_plan", []) if isinstance(gold, dict) and isinstance(gold.get("action_plan"), list) else []:
            if isinstance(action, dict) and "parameters" not in action and "explicit_parameters" in action:
                action["parameters"] = action.pop("explicit_parameters")
                changes.append(f"{wrapper.get('intent_id', '?')}:explicit_parameters->parameters")
    return value, changes


def adjudication_prompt(case: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str]:
    system = "You are the third independent adjudicator. " + protocol_excerpt() + " Compare Pass A and Pass B only against the supplied query/evidence and frozen rules. Do not choose based on completeness or any method preference. Return one repaired/accepted gold_by_intent wrapper only."
    user = json.dumps({"chain": case["chain"], "intents": case["intents"], "pass_a": a, "pass_b": b}, ensure_ascii=False, separators=(",", ":"))
    return system, user


def run_annotation_pass(cases: list[dict[str, Any]], pass_name: str, client: DeepSeekClient, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted: dict[str, dict[str, Any]] = {}
    for case in cases:
        chain_id = case["chain"]["chain_id"]
        path = out_dir / f"{chain_id}.json"
        if path.exists():
            saved = read_json(path)
            if saved.get("status") in {"accepted", "REVIEW_UNRESOLVED"}:
                accepted[chain_id] = saved
                continue
        system, user = build_prompt(case, pass_name)
        initial_raw = client.call(system, user, f"{pass_name}:{chain_id}")
        raw, structural_changes = normalize_structural_aliases(initial_raw)
        errors: dict[str, list[str]] = {}
        try:
            golds = unwrap_results(raw, case["intents"])
            for intent in case["intents"]:
                errors[intent["intent_id"]] = validate_gold(golds[intent["intent_id"]], intent, case["chain"])
        except Exception as exc:
            golds = {}
            errors = {"wrapper": [str(exc)]}
        repaired = False
        if any(errors.values()):
            repaired = True
            repair_system, repair_user = repair_prompt(case, raw, errors)
            repaired_raw = client.call(repair_system, repair_user, f"repair:{pass_name}:{chain_id}")
            raw, repair_structural_changes = normalize_structural_aliases(repaired_raw)
            structural_changes += repair_structural_changes
            try:
                golds = unwrap_results(raw, case["intents"])
                errors = {intent["intent_id"]: validate_gold(golds[intent["intent_id"]], intent, case["chain"]) for intent in case["intents"]}
            except Exception as exc:
                golds = {}
                errors = {"wrapper": [str(exc)]}
        status = "accepted" if not any(errors.values()) else "REVIEW_UNRESOLVED"
        saved = {"chain_id": chain_id, "split": case["split"], "pass": pass_name, "status": status, "repair_used": repaired, "structural_repairs": structural_changes, "errors": errors, "initial_result": initial_raw, "result": raw, "saved_at": datetime.now().isoformat()}
        write_json(path, saved)
        accepted[chain_id] = saved
    return accepted


def adjudicate_cases(cases: list[dict[str, Any]], pass_a: dict[str, Any], pass_b: dict[str, Any], client: DeepSeekClient, out_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    finals: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    for case in cases:
        chain_id = case["chain"]["chain_id"]
        path = out_dir / f"{chain_id}.json"
        if path.exists() and read_json(path).get("status") in {"accepted_agreement", "adjudicated"}:
            saved = read_json(path)
            finals[chain_id] = saved
            summary[chain_id] = saved.get("summary", {})
            continue
        sa, sb = pass_a[chain_id], pass_b[chain_id]
        try:
            ga = unwrap_results(sa.get("result") or {}, case["intents"])
        except Exception:
            ga = {}
        try:
            gb = unwrap_results(sb.get("result") or {}, case["intents"])
        except Exception:
            gb = {}
        if ga and gb:
            equal = all(canonical_signature(ga[i["intent_id"]]) == canonical_signature(gb[i["intent_id"]]) for i in case["intents"])
            disagreements = [i["intent_id"] for i in case["intents"] if canonical_signature(ga[i["intent_id"]]) != canonical_signature(gb[i["intent_id"]])]
        else:
            equal = False
            disagreements = [i["intent_id"] for i in case["intents"]]
        disagreement_fields = {}
        for intent in case["intents"]:
            intent_id = intent["intent_id"]
            if intent_id not in disagreements:
                continue
            if intent_id not in ga or intent_id not in gb:
                disagreement_fields[intent_id] = ["wrapper_validation"]
                continue
            left, right = ga[intent_id], gb[intent_id]
            fields = []
            for field in ("diagnosis", "applicable_procedure", "verification_or_uncertainty", "recommended_actions", "supporting_evidence_ids"):
                if json.dumps(left["work_order"].get(field), ensure_ascii=False, sort_keys=True) != json.dumps(right["work_order"].get(field), ensure_ascii=False, sort_keys=True):
                    fields.append(f"work_order.{field}")
            if json.dumps(left.get("action_plan"), ensure_ascii=False, sort_keys=True) != json.dumps(right.get("action_plan"), ensure_ascii=False, sort_keys=True):
                fields.append("action_plan")
            disagreement_fields[intent_id] = fields
        adjudication_structural_changes: list[str] = []
        if equal:
            final_result = sa["result"]
            status = "accepted_agreement"
            used_adjudication = False
            try:
                gf = unwrap_results(final_result, case["intents"])
                errors = {i["intent_id"]: validate_gold(gf[i["intent_id"]], i, case["chain"]) for i in case["intents"]}
            except Exception as exc:
                errors = {"wrapper": [str(exc)]}
            if any(errors.values()):
                repair_system, repair_user = repair_prompt(case, final_result, errors)
                final_result = client.call(repair_system, repair_user, f"repair:adjudication:{chain_id}:equal")
                final_result, repair_structural_changes = normalize_structural_aliases(final_result)
                adjudication_structural_changes += repair_structural_changes
                try:
                    gf = unwrap_results(final_result, case["intents"])
                    errors = {i["intent_id"]: validate_gold(gf[i["intent_id"]], i, case["chain"]) for i in case["intents"]}
                except Exception as exc:
                    errors = {"wrapper": [str(exc)]}
                status = "accepted_agreement" if not any(errors.values()) else "REVIEW_UNRESOLVED"
        else:
            system, user = adjudication_prompt(case, sa["result"], sb["result"])
            final_result = client.call(system, user, f"adjudication:{chain_id}")
            final_result, adjudication_structural_changes = normalize_structural_aliases(final_result)
            used_adjudication = True
            try:
                gf = unwrap_results(final_result, case["intents"])
                errors = {i["intent_id"]: validate_gold(gf[i["intent_id"]], i, case["chain"]) for i in case["intents"]}
            except Exception as exc:
                errors = {"wrapper": [str(exc)]}
            if any(errors.values()):
                repair_system, repair_user = repair_prompt(case, final_result, errors)
                final_result = client.call(repair_system, repair_user, f"repair:adjudication:{chain_id}")
                final_result, repair_structural_changes = normalize_structural_aliases(final_result)
                adjudication_structural_changes += repair_structural_changes
                try:
                    gf = unwrap_results(final_result, case["intents"])
                    errors = {i["intent_id"]: validate_gold(gf[i["intent_id"]], i, case["chain"]) for i in case["intents"]}
                except Exception as exc:
                    errors = {"wrapper": [str(exc)]}
            status = "adjudicated" if not any(errors.values()) else "REVIEW_UNRESOLVED"
        if not equal:
            try:
                gf = unwrap_results(final_result, case["intents"])
                errors = {i["intent_id"]: validate_gold(gf[i["intent_id"]], i, case["chain"]) for i in case["intents"]}
            except Exception as exc:
                errors = {"wrapper": [str(exc)]}
            if any(errors.values()):
                status = "REVIEW_UNRESOLVED"
        saved = {"chain_id": chain_id, "split": case["split"], "status": status, "used_adjudication": used_adjudication, "structural_repairs": adjudication_structural_changes, "disagreement_intents": disagreements, "disagreement_fields": disagreement_fields, "summary": {"pass_a_pass_b_canonical_equal": equal, "disagreement_count": len(disagreements), "disagreement_fields": disagreement_fields}, "result": final_result if status != "REVIEW_UNRESOLVED" else None}
        write_json(path, saved)
        finals[chain_id] = saved
        summary[chain_id] = saved["summary"]
    return finals, summary


def schema_document() -> dict[str, Any]:
    citation = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "tef-rag-v6-generation-gold-v1",
        "type": "object", "additionalProperties": False, "required": ["work_order", "action_plan"],
        "properties": {
            "work_order": {"type": "object", "additionalProperties": False, "required": ["asset_id", "diagnosis", "recommended_actions", "applicable_procedure", "verification_or_uncertainty", "supporting_evidence_ids"], "properties": {
                "asset_id": {"type": "string"},
                "diagnosis": {"type": "object", "additionalProperties": False, "required": ["status", "concept", "supporting_evidence_ids"], "properties": {"status": {"enum": sorted(DIAG_STATUSES)}, "concept": {"type": ["string", "null"]}, "supporting_evidence_ids": citation}},
                "recommended_actions": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                "applicable_procedure": {"type": "object", "additionalProperties": False, "required": ["status", "procedure_version", "supporting_evidence_ids"], "properties": {"status": {"enum": sorted(PROC_STATUSES)}, "procedure_version": {"type": ["string", "null"]}, "supporting_evidence_ids": citation}},
                "verification_or_uncertainty": {"type": "object", "additionalProperties": False, "required": ["status", "statement", "supporting_evidence_ids"], "properties": {"status": {"enum": sorted(VERIF_STATUSES)}, "statement": {"type": ["string", "null"]}, "supporting_evidence_ids": citation}},
                "supporting_evidence_ids": citation,
            }},
            "action_plan": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["action_id", "action_type", "target", "parameters", "depends_on", "supporting_evidence_ids"], "properties": {"action_id": {"type": "string"}, "action_type": {"enum": sorted(ACTION_TYPES)}, "target": {"type": ["string", "null"]}, "parameters": {"type": "object"}, "depends_on": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}, "supporting_evidence_ids": citation}}},
        },
    }


def write_registries() -> None:
    metadata = OUT / "metadata"
    write_json(metadata / "schema.json", schema_document())
    write_json(metadata / "alias_registry.json", {"version": "generation-canonical-v1", "unicode": "NFKC", "status_aliases": {"confirmed": ["confirmed", "确诊", "确认"], "provisional": ["provisional", "初步", "疑似"], "persistent_uncertainty": ["persistent_uncertainty", "持续不确定", "无法确认"], "not_available": ["not_available", "未知", "无证据"]}, "action_type_aliases": {"inspect": ["inspect", "inspection", "检查", "核查"], "diagnose": ["diagnose", "diagnosis", "诊断", "分析"], "isolate": ["isolate", "隔离"], "adjust": ["adjust", "调整", "恢复参数"], "repair": ["repair", "维修", "修复", "处理"], "replace": ["replace", "更换"], "verify": ["verify", "verification", "验证", "复测"], "monitor": ["monitor", "监测", "观察"], "document": ["document", "记录", "归档"]}, "unknown_policy": "canonicalized_raw_phrase; no fuzzy matching"})
    write_json(metadata / "parameter_registry.json", {"version": "generation-parameter-v1", "name_policy": "canonicalized evidence phrase; no common-sense additions", "unit_policy": "explicit evidence units only; normalize equivalent SI spellings", "numeric_tolerance": 1e-6, "aliases": {"temperature": ["temperature", "温度"], "voltage": ["voltage", "电压"], "current": ["current", "电流"], "resistance": ["resistance", "电阻"], "pressure": ["pressure", "压力"], "time": ["time", "时间"], "rate": ["rate", "速率"]}})


def write_outputs(cases_by_split: dict[str, list[dict[str, Any]]], finals_by_split: dict[str, dict[str, Any]], summaries_by_split: dict[str, dict[str, Any]], client: DeepSeekClient, private_root: Path) -> dict[str, Any]:
    public_dir = OUT / "public"
    metadata = OUT / "metadata"
    qa: dict[str, Any] = {"splits": {}, "all_checks_pass": True}
    counts: dict[str, int] = {}
    public_hashes: dict[str, str] = {}
    private_hash = None
    for split, cases in cases_by_split.items():
        rows: list[dict[str, Any]] = []
        index_rows: list[dict[str, Any]] = []
        split_qa = {"semantic_gold_objects": 0, "schema_valid": 0, "temporal_valid": 0, "citation_valid": 0, "dag_valid": 0, "paraphrase_consistent": 0, "review_unresolved": 0}
        for case in cases:
            saved = finals_by_split[split][case["chain"]["chain_id"]]
            if saved.get("status") == "REVIEW_UNRESOLVED":
                split_qa["review_unresolved"] += len(case["intents"])
                continue
            golds = unwrap_results(saved["result"], case["intents"])
            for intent in case["intents"]:
                gold = golds[intent["intent_id"]]
                errors = validate_gold(gold, intent, case["chain"])
                split_qa["semantic_gold_objects"] += 1
                if not errors:
                    split_qa["schema_valid"] += 1
                    split_qa["temporal_valid"] += 1
                    split_qa["citation_valid"] += 1
                    split_qa["dag_valid"] += 1
                    split_qa["paraphrase_consistent"] += 1
                semantic_id = f"{case['chain']['chain_id']}::{intent['intent_id']}"
                rows.append(gold)
                index_rows.append({"semantic_gold_id": semantic_id, "chain_id": case["chain"]["chain_id"], "intent_id": intent["intent_id"], "query_ids": [q["query_id"] for q in intent["queries"]], "split": split, "query_times": [q["query_time"] for q in intent["queries"]], "visible_evidence_count": len(intent["visible_evidence_ids"])})
        target_dir = public_dir if split != "test" else private_root
        target_dir.mkdir(parents=True, exist_ok=True)
        gold_path = target_dir / f"gold_{split}.jsonl"
        index_path = target_dir / f"gold_{split}_index.jsonl"
        write_jsonl(gold_path, rows)
        write_jsonl(index_path, index_rows)
        counts[split] = len(rows)
        qa["splits"][split] = split_qa
        if split != "test":
            public_hashes[str(gold_path.relative_to(ROOT))] = sha(gold_path)
            public_hashes[str(index_path.relative_to(ROOT))] = sha(index_path)
        else:
            private_hash = sha(gold_path)
    qa["all_checks_pass"] = all(item.get("review_unresolved", 0) == 0 for item in qa["splits"].values())
    write_json(metadata / "annotation_qa.json", qa)
    disagreement = {split: {"chains": len(cases_by_split[split]), "adjudicated_chains": sum(1 for row in finals_by_split[split].values() if row.get("used_adjudication")), "disagreement_intents": sum(len(row.get("disagreement_intents", [])) for row in finals_by_split[split].values()), "disagreement_fields": {field: sum(1 for row in finals_by_split[split].values() for fields in row.get("disagreement_fields", {}).values() if field in fields) for field in ("work_order.diagnosis", "work_order.applicable_procedure", "work_order.verification_or_uncertainty", "work_order.recommended_actions", "work_order.supporting_evidence_ids", "action_plan")}, "review_unresolved_chains": sum(1 for row in finals_by_split[split].values() if row.get("status") == "REVIEW_UNRESOLVED")} for split in cases_by_split}
    write_json(metadata / "disagreement_summary.json", disagreement)
    write_json(metadata / "test_generation_gold_aggregate.json", {"split": "test", "chains": len(cases_by_split.get("test", [])), "semantic_gold_objects": counts.get("test", 0), "private_gold_sha256": private_hash, "item_level_gold_committed": False})
    manifest = {"protocol": str(PROTOCOL.relative_to(ROOT)), "protocol_sha256": sha(PROTOCOL), "benchmark_seal_commit": SEAL_COMMIT, "branch": "tef-rag-v6-generation-gold-v1", "chain_counts": {split: len(cases_by_split[split]) for split in cases_by_split}, "semantic_gold_counts": counts, "public_hashes": public_hashes, "private_test_gold_sha256": private_hash, "deepseek": {"base_url": BASE_URL, "model": MODEL, "temperature": TEMPERATURE, "api_key_persisted": False}, "llm_runtime": client.stats, "retrieval_predictions_accessed": False, "retrieval_test_metrics_accessed": False, "retrieval_sealed_evaluator_accessed": False, "generation_evaluation_run": False, "review_unresolved": sum(v["review_unresolved_chains"] for v in disagreement.values()), "generation_gold_ready": qa["all_checks_pass"]}
    write_json(metadata / "annotation_manifest.json", manifest)
    report = ["# TEF-RAG v6 generation gold v1", "", "Generation gold was authored from public query/chain/evidence only under the frozen v1 protocol. Retrieval predictions, retrieval test metrics, sealed evaluator, and private blind-review artifacts were not read.", "", f"- Branch base: `{SEAL_COMMIT}`", f"- Semantic objects: development={counts.get('development', 0)}, validation={counts.get('validation', 0)}, test={counts.get('test', 0)} (test gold private)", f"- Passes: sequential independent Pass A and Pass B; conflicts adjudicated in a fresh context", f"- DeepSeek: `{MODEL}`, temperature `{TEMPERATURE}`, requests `{client.stats['requests']}`, cache hits `{client.stats['cache_hits']}`, failures `{client.stats['failures']}`", f"- REVIEW_UNRESOLVED: {manifest['review_unresolved']}", f"- GENERATION_GOLD_READY: {manifest['generation_gold_ready']}", "", "## QA", "", "```json", json.dumps(qa, ensure_ascii=False, indent=2), "```", ""]
    (ROOT / "markdowns/tef_rag_v6_generation_gold_v1.md").write_text("\n".join(report), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    parser.add_argument("--private-root", default=str(PRIVATE))
    parser.add_argument("--limit", type=int, default=None, help="development-only bounded smoke run; omit for the formal run")
    parser.add_argument("--offline-finalize", action="store_true", help="write aggregate/public outputs from existing A/B/adjudication files without API calls")
    parser.add_argument("--retry-unresolved", action="store_true", help="reuse Pass A/B cache but use a fresh cache namespace for unresolved adjudication/repair calls")
    args = parser.parse_args()
    if not PROTOCOL.exists():
        raise RuntimeError("frozen protocol missing")
    OUT.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(parents=True, exist_ok=True)
    private_root = Path(args.private_root)
    write_registries()
    cases_by_split = {split: build_cases(split) for split in args.splits}
    if args.limit is not None:
        cases_by_split = {split: cases[:args.limit] for split, cases in cases_by_split.items()}
    if args.offline_finalize:
        finals: dict[str, dict[str, Any]] = {}
        summaries: dict[str, dict[str, Any]] = {}
        for split, cases in cases_by_split.items():
            directory = (RUN / "adjudication") if split != "test" else (private_root / "adjudication")
            finals[split] = {}
            summaries[split] = {}
            for case in cases:
                chain_id = case["chain"]["chain_id"]
                path = directory / f"{chain_id}.json"
                if path.exists():
                    saved = read_json(path)
                else:
                    saved = {"chain_id": chain_id, "split": split, "status": "REVIEW_UNRESOLVED", "summary": {"reason": "missing adjudication record"}}
                finals[split][chain_id] = saved
                summaries[split][chain_id] = saved.get("summary", {})
        cache_files = list((RUN / "api_cache").glob("*.json")) + list((private_root / "api_cache").glob("*.json"))
        aggregate_stats = {"requests": len(cache_files), "cache_hits": 0, "retries": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for path in cache_files:
            try:
                record = read_json(path)
                usage = record.get("usage") or {}
                aggregate_stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                aggregate_stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                aggregate_stats["total_tokens"] += int(usage.get("total_tokens") or 0)
            except Exception:
                aggregate_stats["failures"] += 1
        aggregate_client = object.__new__(DeepSeekClient)
        aggregate_client.stats = aggregate_stats
        write_outputs(cases_by_split, finals, summaries, aggregate_client, private_root)
        print(json.dumps({"status": "offline-finalized", "llm": aggregate_stats}, ensure_ascii=False))
        return
    pass_a: dict[str, dict[str, Any]] = {}
    pass_b: dict[str, dict[str, Any]] = {}
    finals: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    aggregate_stats = {"requests": 0, "cache_hits": 0, "retries": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for split, cases in cases_by_split.items():
        cache_dir = (private_root / "api_cache") if split == "test" else (RUN / "api_cache")
        client = DeepSeekClient(cache_dir)
        pass_a[split] = run_annotation_pass(cases, "A", client, (RUN / "pass_a") if split != "test" else (private_root / "pass_a"))
        pass_b[split] = run_annotation_pass(cases, "B", client, (RUN / "pass_b") if split != "test" else (private_root / "pass_b"))
        if args.retry_unresolved:
            retry_dir = (private_root / "api_retry_cache") if split == "test" else (RUN / "api_retry_cache")
            adjudication_client = DeepSeekClient(retry_dir)
        else:
            adjudication_client = client
        finals[split], summaries[split] = adjudicate_cases(cases, pass_a[split], pass_b[split], adjudication_client, (RUN / "adjudication") if split != "test" else (private_root / "adjudication"))
        for active_client in ([client] if adjudication_client is client else [client, adjudication_client]):
            for key in aggregate_stats:
                aggregate_stats[key] += active_client.stats[key]
    aggregate_client = object.__new__(DeepSeekClient)
    aggregate_client.stats = aggregate_stats
    write_outputs(cases_by_split, finals, summaries, aggregate_client, private_root)
    print(json.dumps({"status": "complete", "splits": {split: len(cases) for split, cases in cases_by_split.items()}, "llm": aggregate_stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
