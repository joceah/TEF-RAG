"""Query-conditioned LLM relation scoring with deterministic prefilter/cache."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable
from urllib import request
from urllib.error import HTTPError


NO_EDGE = "NO_EDGE"
REASON_CODES = (
    "no_direct_query_flow", "semantic_support", "procedure_governance", "later_update",
    "verification", "qualification", "uncertainty_preserved", "uncertainty_resolved",
    "contrast", "prerequisite", "supersession", "other_direct_flow",
)
RELATION_CODES = {
    "N": NO_EDGE, "C": "contrasts", "G": "governs", "P": "prerequisite",
    "U": "preserves_uncertainty", "Q": "qualifies", "R": "resolves",
    "X": "supersession", "S": "supports", "D": "updates", "V": "verifies",
}
REASON_RELATIONS = {
    0: NO_EDGE, 1: "supports", 2: "governs", 3: "updates", 4: "verifies",
    5: "qualifies", 6: "preserves_uncertainty", 7: "resolves", 8: "contrasts",
    9: "prerequisite", 10: "supersession", 11: "supports",
}


@dataclass(frozen=True)
class LLMRelationConfig:
    base_url: str = "http://127.0.0.1:55555"
    endpoint: str | None = None
    model: str = "deepseek-chat"
    thinking: str | None = None
    prompt_version: str = "tef-v6-stage2a-relation-v7"
    temperature: float = 0.0
    max_tokens: int = 1800
    timeout_seconds: float = 120.0
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    busy_retry_backoff_seconds: float = 30.0
    request_interval_seconds: float = 3.0
    max_pairs_per_query: int = 16
    batch_size: int = 16
    cases_per_request: int = 8
    case_batch_mode: bool = False
    llm_confidence_threshold: float = 0.60
    hybrid_llm_weight: float = 0.75
    prefilter_heuristic_floor: float = 0.52
    cache_dir: str = ".cache/tef_rag_v6_llm_relation"

    @classmethod
    def from_dict(cls, value: dict) -> "LLMRelationConfig":
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown LLM relation config fields: {sorted(unknown)}")
        return cls(**value)


def prompt_text(taxonomy: dict, version: str) -> str:
    definitions = "; ".join(
        f"{name}: {description}" for name, description in sorted(taxonomy.items())
    )
    relation_codes = ", ".join(f"{code}={name}" for code, name in RELATION_CODES.items())
    reason_codes = ", ".join(f"{index}={name}" for index, name in enumerate(REASON_CODES))
    return (
        f"Prompt version: {version}. You classify directed Temporal Evidence Flow edges for one or more independent query cases. "
        "Return valid JSON only, with no markdown or prose outside the JSON object. "
        "Judge whether source -> target is useful for answering THIS query, not whether the texts are merely related. "
        "Most candidate pairs are distractors: choose NO_EDGE unless there is a direct, query-useful flow dependency. "
        "Shared asset, episode, topic, or chronology alone never licenses an edge. "
        "Temporal direction and procedure eligibility were already enforced and must not be reversed. "
        f"Allowed relation types: {definitions}. Otherwise use NO_EDGE. "
        "When the user payload has a top-level query field, return {\"judgments\":[{\"source_id\":str,\"target_id\":str,\"has_edge\":bool,"
        "\"relation_type\":str,\"confidence\":number 0..1,\"reason_code\":short_snake_case}]}. "
        f"When the user payload has a top-level cases field, even if cases contains exactly one item, use relation codes {relation_codes}; reason codes {reason_codes}. "
        "Pairs are ordered. Return {\"cases\":[[case_id,[[relation_code,confidence_percent,reason_code],...]],...]}. "
        "Each inner result list must have exactly the same length and order as that case's supplied pairs. "
        "The user supplies deduplicated evidence tables and source_id/target_id pairs. Do not mix facts across "
        "cases. Do not repeat evidence IDs. Do not provide prose or hidden reasoning."
    )


def _recover_json(text: str) -> object:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class LLMRelationClient:
    def __init__(
        self,
        config: LLMRelationConfig,
        taxonomy: dict,
        *,
        api_key: str | None = None,
        transport: Callable[[dict, float], dict] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.taxonomy = dict(taxonomy)
        self.allowed = frozenset(taxonomy)
        if frozenset(RELATION_CODES.values()) != self.allowed | {NO_EDGE}:
            raise ValueError("relation code map does not match frozen taxonomy")
        self.relation_by_code = dict(RELATION_CODES)
        self.api_key = api_key or os.environ.get("TEF_RAG_LLM_API_KEY", "sk-any")
        self.transport = transport or self._http_transport
        self.sleep = sleep
        self.system_prompt = prompt_text(self.taxonomy, config.prompt_version)
        self.cache_dir = Path(config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._log_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_finished = 0.0

    def _http_transport(self, payload: dict, timeout: float) -> dict:
        target = self.config.endpoint or (self.config.base_url.rstrip("/") + "/v1/chat/completions")
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            target,
            data=encoded,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            exc.msg = f"{exc.msg}; response={body[:500]}"
            raise

    def _serial_transport(self, payload: dict) -> dict:
        """Keep exactly one UI-backed API request in flight and pace calls."""
        with self._request_lock:
            remaining = self.config.request_interval_seconds - (
                time.monotonic() - self._last_request_finished
            )
            if remaining > 0:
                self.sleep(remaining)
            try:
                return self.transport(payload, self.config.timeout_seconds)
            finally:
                self._last_request_finished = time.monotonic()

    @staticmethod
    def _evidence_view(document: dict) -> dict:
        keys = (
            "evidence_id", "text", "event_type", "source_type", "event_time", "available_at",
            "episode_id", "chain_id", "procedure_version", "valid_from", "valid_to", "withdrawn_at",
            "model_scope", "supersedes",
        )
        return {key: document.get(key) for key in keys if document.get(key) is not None}

    def _cache_payload(self, query: dict, source: dict, target: dict) -> dict:
        return {
            "model": self.config.model,
            "endpoint": self.config.endpoint or self.config.base_url,
            "thinking": self.config.thinking,
            "prompt_version": self.config.prompt_version,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "query": {
                "query_text": query["query_text"], "query_time": query["query_time"],
                "asset_model": query.get("asset_model", ""), "asset_context": query.get("asset_context", ""),
            },
            "source": self._evidence_view(source),
            "target": self._evidence_view(target),
        }

    def fingerprint(self, query: dict, source: dict, target: dict) -> str:
        raw = json.dumps(
            self._cache_payload(query, source, target), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _cache_path(self, fingerprint: str) -> Path:
        return self.cache_dir / fingerprint[:2] / f"{fingerprint}.json"

    def _load_cache(self, fingerprint: str) -> dict | None:
        path = self._cache_path(fingerprint)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("fingerprint") == fingerprint:
                judgment = value["judgment"]
                if judgment.get("reason_code") != "client_failure_after_retries":
                    return judgment
        except (OSError, KeyError, json.JSONDecodeError):
            return None
        return None

    def _save_cache(self, fingerprint: str, judgment: dict) -> None:
        path = self._cache_path(fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps({"fingerprint": fingerprint, "judgment": judgment}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _failure_log(self, value: dict) -> None:
        path = self.cache_dir / "failures.jsonl"
        with self._log_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _validate(self, raw: dict, source_id: str, target_id: str) -> tuple[dict, bool]:
        if not isinstance(raw, dict):
            raise ValueError("judgment is not an object")
        if raw.get("source_id") != source_id or raw.get("target_id") != target_id:
            raise ValueError("judgment endpoint mismatch")
        has_edge = raw.get("has_edge") is True
        relation = str(raw.get("relation_type", NO_EDGE))
        invalid_type = has_edge and relation not in self.allowed
        if invalid_type:
            has_edge, relation = False, NO_EDGE
        if not has_edge:
            relation = NO_EDGE
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = re.sub(r"[^a-z0-9_]+", "_", str(raw.get("reason_code", "unspecified")).lower()).strip("_")
        return {
            "source_id": source_id, "target_id": target_id, "has_edge": has_edge,
            "relation_type": relation, "confidence": confidence,
            "reason_code": reason[:80] or "unspecified",
        }, invalid_type

    def _request_batch(self, query: dict, pairs: list[dict]) -> tuple[dict, dict]:
        evidence = {}
        for pair in pairs:
            evidence[pair["source"]["evidence_id"]] = self._evidence_view(pair["source"])
            evidence[pair["target"]["evidence_id"]] = self._evidence_view(pair["target"])
        user = {
            "query": {
                "query_text": query["query_text"], "query_time": query["query_time"],
                "asset_model": query.get("asset_model", ""), "asset_context": query.get("asset_context", ""),
            },
            "evidence": [evidence[identifier] for identifier in sorted(evidence)],
            "pairs": [
                {"source_id": pair["source"]["evidence_id"], "target_id": pair["target"]["evidence_id"]}
                for pair in pairs
            ],
        }
        payload = {
            "model": self.config.model, "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))},
            ],
        }
        if self.config.thinking:
            payload["thinking"] = {"type": self.config.thinking}
        diagnostics = {"request_count": 0, "retry_count": 0, "malformed_count": 0, "latency_seconds": 0.0,
                       "prompt_tokens": 0, "completion_tokens": 0, "invalid_type_count": 0}
        expected = {(pair["source"]["evidence_id"], pair["target"]["evidence_id"]) for pair in pairs}
        last_error = "unknown"
        last_response_shape = None
        last_response_symbols = None

        for attempt in range(self.config.max_retries + 1):
            diagnostics["request_count"] += 1
            started = time.perf_counter()
            try:
                response = self._serial_transport(payload)
                diagnostics["latency_seconds"] += time.perf_counter() - started
                usage = response.get("usage") or {}
                diagnostics["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                diagnostics["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                parsed = _recover_json(response["choices"][0]["message"]["content"])
                def response_shape(value, depth=0):
                    if depth >= 4:
                        return type(value).__name__
                    if isinstance(value, dict):
                        return {str(key): response_shape(item, depth + 1) for key, item in value.items()}
                    if isinstance(value, list):
                        return {"list_length": len(value), "items": [response_shape(item, depth + 1) for item in value[:2]]}
                    return type(value).__name__
                last_response_shape = response_shape(parsed)
                def response_symbols(value):
                    output = []
                    if isinstance(value, list):
                        if len(value) == 3 and all(not isinstance(item, (list, dict)) for item in value):
                            output.append([str(value[0])[:80], str(value[1])[:80], str(value[2])[:80]])
                        else:
                            for item in value:
                                output.extend(response_symbols(item))
                    elif isinstance(value, dict):
                        for item in value.values():
                            output.extend(response_symbols(item))
                    return sorted({tuple(item) for item in output})
                last_response_symbols = response_symbols(parsed)
                rows = parsed.get("judgments") if isinstance(parsed, dict) else None
                compact = parsed.get("cases") if isinstance(parsed, dict) else None
                def compact_results(value):
                    if (isinstance(value, list) and len(value) == len(pairs)
                            and all(isinstance(item, list) and len(item) == 3
                                    and (str(item[0]).upper() in self.relation_by_code
                                         or str(item[0]) in self.allowed | {NO_EDGE}) for item in value)):
                        return value
                    if isinstance(value, list):
                        found = [result for item in value if (result := compact_results(item)) is not None]
                        if len(found) == 1:
                            return found[0]
                    return None
                compact_values = compact_results(compact)
                if not isinstance(rows, list) and compact_values is not None:
                    converted = []
                    for pair, result in zip(pairs, compact_values):
                        relation = self.relation_by_code.get(str(result[0]).upper())
                        if relation is None and str(result[0]) in self.allowed | {NO_EDGE}:
                            relation = str(result[0])
                        try:
                            confidence = float(str(result[1]).strip().removesuffix("%"))
                            reason = (str(result[2]) if str(result[2]) in REASON_CODES
                                      else REASON_CODES[int(result[2])])
                        except (IndexError, TypeError, ValueError):
                            relation = None
                        if relation is None:
                            converted = []
                            break
                        converted.append({"source_id": pair["source"]["evidence_id"],
                            "target_id": pair["target"]["evidence_id"],
                            "has_edge": relation != NO_EDGE, "relation_type": relation,
                            "confidence": confidence / 100.0 if confidence > 1.0 else confidence,
                            "reason_code": reason})
                    if converted:
                        rows = converted
                if len(pairs) == 1 and isinstance(parsed, dict) and not isinstance(rows, list):
                    direct = parsed.get("judgment", parsed)
                    if isinstance(direct, dict) and "has_edge" in direct:
                        pair = pairs[0]
                        rows = [{**direct,
                                 "source_id": direct.get("source_id", pair["source"]["evidence_id"]),
                                 "target_id": direct.get("target_id", pair["target"]["evidence_id"])}]
                    compact = parsed.get("cases")
                    if (not isinstance(rows, list) and isinstance(compact, list) and len(compact) == 1
                            and isinstance(compact[0], list) and len(compact[0]) == 2
                            and isinstance(compact[0][1], list) and len(compact[0][1]) == 1):
                        result = compact[0][1][0]
                        if isinstance(result, list) and len(result) == 3:
                            relation = self.relation_by_code.get(str(result[0]).upper())
                            try:
                                confidence = float(result[1])
                                reason = REASON_CODES[int(result[2])]
                            except (IndexError, TypeError, ValueError):
                                relation = None
                            if relation is not None:
                                pair = pairs[0]
                                rows = [{"source_id": pair["source"]["evidence_id"],
                                         "target_id": pair["target"]["evidence_id"],
                                         "has_edge": relation != NO_EDGE, "relation_type": relation,
                                         "confidence": confidence / 100.0 if confidence > 1.0 else confidence,
                                         "reason_code": reason}]
                if not isinstance(rows, list):
                    raise ValueError("response has no judgments array")
                output = {}
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    key = (raw.get("source_id"), raw.get("target_id"))
                    if key not in expected or key in output:
                        continue
                    value, invalid = self._validate(raw, key[0], key[1])
                    diagnostics["invalid_type_count"] += int(invalid)
                    output[key] = value
                if set(output) != expected:
                    raise ValueError(f"missing judgments: {len(expected) - len(output)}")
                return output, diagnostics
            except Exception as exc:
                diagnostics["latency_seconds"] += time.perf_counter() - started
                last_error = f"{type(exc).__name__}:{str(exc)[:160]}"
                diagnostics["malformed_count"] += int(isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)))
                if attempt < self.config.max_retries:
                    diagnostics["retry_count"] += 1
                    busy = isinstance(exc, HTTPError) and exc.code == 429
                    base = (
                        self.config.busy_retry_backoff_seconds
                        if busy else self.config.retry_backoff_seconds
                    )
                    self.sleep(base * (attempt + 1))
        self._failure_log({
            "prompt_version": self.config.prompt_version,
            "query_fingerprint": hashlib.sha256(query["query_text"].encode("utf-8")).hexdigest(),
            "pair_count": len(pairs), "error": last_error, "response_shape": last_response_shape,
            "response_symbols": last_response_symbols,
        })
        failure = {
            (pair["source"]["evidence_id"], pair["target"]["evidence_id"]): {
                "source_id": pair["source"]["evidence_id"], "target_id": pair["target"]["evidence_id"],
                "has_edge": False, "relation_type": NO_EDGE, "confidence": 0.0,
                "reason_code": "client_failure_after_retries",
            }
            for pair in pairs
        }
        return failure, diagnostics

    def _request_case_batch(self, cases: list[dict]) -> tuple[dict | None, dict]:
        user_cases = []
        expected = set()
        for case in cases:
            evidence = {}
            for pair in case["pairs"]:
                evidence[pair["source"]["evidence_id"]] = self._evidence_view(pair["source"])
                evidence[pair["target"]["evidence_id"]] = self._evidence_view(pair["target"])
                expected.add((case["case_id"], pair["source"]["evidence_id"], pair["target"]["evidence_id"]))
            query = case["query"]
            user_cases.append({
                "case_id": case["case_id"],
                "query": {
                    "query_text": query["query_text"], "query_time": query["query_time"],
                    "asset_model": query.get("asset_model", ""),
                    "asset_context": query.get("asset_context", ""),
                },
                "evidence": [evidence[identifier] for identifier in sorted(evidence)],
                "pairs": [[pair["source"]["evidence_id"], pair["target"]["evidence_id"]] for pair in case["pairs"]],
            })
        payload = {
            "model": self.config.model, "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens, "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps({"cases": user_cases}, ensure_ascii=False, separators=(",", ":"))},
            ],
        }
        if self.config.thinking:
            payload["thinking"] = {"type": self.config.thinking}
        diagnostics = {
            "case_count": len(cases), "pair_count": len(expected), "request_count": 0,
            "retry_count": 0, "malformed_count": 0, "latency_seconds": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "invalid_type_count": 0,
            "failed_batch_count": 0, "padded_missing_count": 0,
        }
        last_error = "unknown"

        def decode_aligned(case: dict, results: list) -> dict | None:
            expected_count = len(case["pairs"])
            if len(results) > expected_count:
                extras = results[expected_count:]
                if not all(
                    isinstance(item, list) and len(item) == 3
                    and (str(item[0]).upper() in {"N", "NO_EDGE", "0"})
                    for item in extras
                ):
                    return None
                results = results[:expected_count]
            if len(results) < expected_count:
                missing_count = expected_count - len(results)
                results = list(results) + [["N", 0, 0] for _ in range(missing_count)]
                diagnostics["padded_missing_count"] += missing_count
            decoded = {}
            for pair, result in zip(case["pairs"], results):
                if not isinstance(result, list) or len(result) != 3:
                    return None
                source_id = pair["source"]["evidence_id"]
                target_id = pair["target"]["evidence_id"]
                relation_token = str(result[0])
                relation = self.relation_by_code.get(relation_token.upper())
                if relation is None and relation_token in self.allowed | {NO_EDGE}:
                    relation = relation_token
                if relation is None:
                    try:
                        relation_code = int(result[0])
                        reason_code = int(result[2])
                    except (TypeError, ValueError):
                        pass
                    else:
                        if relation_code == reason_code:
                            relation = REASON_RELATIONS.get(reason_code)
                try:
                    confidence = float(result[1])
                    confidence = confidence / 100.0 if confidence > 1.0 else confidence
                except (TypeError, ValueError):
                    return None
                try:
                    reason = REASON_CODES[int(result[2])]
                except (IndexError, TypeError, ValueError):
                    reason = re.sub(r"[^a-z0-9_]+", "_", str(result[2]).lower()).strip("_")
                if relation is None:
                    return None
                raw = {
                    "source_id": source_id, "target_id": target_id,
                    "has_edge": relation != NO_EDGE, "relation_type": relation,
                    "confidence": confidence, "reason_code": reason,
                }
                value, invalid = self._validate(raw, source_id, target_id)
                diagnostics["invalid_type_count"] += int(invalid)
                decoded[(case["case_id"], source_id, target_id)] = value
            return decoded

        for attempt in range(self.config.max_retries + 1):
            diagnostics["request_count"] += 1
            started = time.perf_counter()
            try:
                response = self._serial_transport(payload)
                diagnostics["latency_seconds"] += time.perf_counter() - started
                usage = response.get("usage") or {}
                diagnostics["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                diagnostics["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                parsed = _recover_json(response["choices"][0]["message"]["content"])
                rows = parsed.get("cases") if isinstance(parsed, dict) else None
                if (
                    isinstance(rows, list) and len(rows) == 1
                    and isinstance(rows[0], list) and len(rows[0]) == 1
                    and isinstance(rows[0][0], list)
                ):
                    rows = rows[0]
                if len(cases) == 1 and isinstance(parsed, dict):
                    case = cases[0]
                    aligned = parsed.get("results")
                    if not isinstance(aligned, list):
                        judgments = parsed.get("judgments")
                        if isinstance(judgments, list) and all(isinstance(item, list) for item in judgments):
                            aligned = judgments
                    if isinstance(rows, list) and len(rows) == 1:
                        row = rows[0]
                        if isinstance(row, list) and len(row) == 2 and isinstance(row[1], list):
                            aligned = row[1]
                        elif isinstance(row, dict):
                            candidate = row.get("results", row.get("judgments"))
                            if isinstance(candidate, list):
                                aligned = candidate
                    if isinstance(aligned, list):
                        output = decode_aligned(case, aligned)
                        if output is not None and set(output) == expected:
                            return output, diagnostics
                    verbose = parsed.get("judgments")
                    if isinstance(verbose, list):
                        case_id = case["case_id"]
                        output = {}
                        case_expected = {
                            (pair["source"]["evidence_id"], pair["target"]["evidence_id"])
                            for pair in case["pairs"]
                        }
                        for raw in verbose:
                            if not isinstance(raw, dict):
                                continue
                            key = (raw.get("source_id"), raw.get("target_id"))
                            if key not in case_expected or (case_id, *key) in output:
                                continue
                            value, invalid = self._validate(raw, key[0], key[1])
                            diagnostics["invalid_type_count"] += int(invalid)
                            output[(case_id, *key)] = value
                        if set(output) == expected:
                            return output, diagnostics
                if not isinstance(rows, list):
                    raise ValueError("response has no cases array")
                output = {}
                for row in rows:
                    if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], list):
                        continue
                    case_id, results = row
                    case = next((value for value in cases if value["case_id"] == case_id), None)
                    if case is None or len(results) != len(case["pairs"]):
                        continue
                    decoded = decode_aligned(case, results)
                    if decoded is not None:
                        output.update(decoded)
                if set(output) != expected:
                    raise ValueError(f"missing judgments: {len(expected) - len(output)}")
                return output, diagnostics
            except Exception as exc:
                diagnostics["latency_seconds"] += time.perf_counter() - started
                last_error = f"{type(exc).__name__}:{str(exc)[:160]}"
                diagnostics["malformed_count"] += int(isinstance(exc, (ValueError, KeyError, json.JSONDecodeError)))
                if attempt < self.config.max_retries:
                    diagnostics["retry_count"] += 1
                    busy = isinstance(exc, HTTPError) and exc.code == 429
                    base = self.config.busy_retry_backoff_seconds if busy else self.config.retry_backoff_seconds
                    self.sleep(base * (attempt + 1))
        diagnostics["failed_batch_count"] = 1
        self._failure_log({
            "prompt_version": self.config.prompt_version, "case_count": len(cases),
            "pair_count": len(expected), "error": last_error,
        })
        return None, diagnostics

    def warm_cases(self, cases: list[dict]) -> dict:
        """Populate pair cache using serial multi-query requests; never runs requests concurrently."""
        pending = []
        cache_hits = 0
        existing = {path.stem for path in self.cache_dir.rglob("*.json")}
        for case in cases:
            missing = []
            for pair in case["pairs"]:
                fingerprint = self.fingerprint(case["query"], pair["source"], pair["target"])
                if fingerprint in existing:
                    cache_hits += 1
                else:
                    missing.append({**pair, "fingerprint": fingerprint})
            if missing:
                pending.append({"case_id": case["case_id"], "query": case["query"], "pairs": missing})
        totals = {
            "case_count": len(cases), "pending_case_count": len(pending), "pair_count": 0,
            "cache_hit_count": cache_hits, "saved_pair_count": 0, "request_count": 0,
            "retry_count": 0, "malformed_count": 0, "latency_seconds": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "invalid_type_count": 0,
            "failed_batch_count": 0, "padded_missing_count": 0,
        }
        for start in range(0, len(pending), self.config.cases_per_request):
            batch = pending[start : start + self.config.cases_per_request]
            judged, diagnostics = self._request_case_batch(batch)
            # The frozen endpoint occasionally emits malformed compact JSON for a
            # single case. Production runs may retry once through the established
            # verbose protocol; max_retries=0 preserves fail-fast test semantics.
            if judged is None and len(batch) == 1 and self.config.max_retries > 0:
                case = batch[0]
                verbose, fallback_diag = self._request_batch(case["query"], case["pairs"])
                if verbose and all(value.get("reason_code") != "client_failure_after_retries"
                                   for value in verbose.values()):
                    judged = {(case["case_id"], source, target): value
                              for (source, target), value in verbose.items()}
                    diagnostics["failed_batch_count"] = 0
                    for key in ("request_count", "retry_count", "malformed_count", "latency_seconds",
                                "prompt_tokens", "completion_tokens", "invalid_type_count"):
                        diagnostics[key] += fallback_diag.get(key, 0)
            if judged is None and len(batch) == 1 and len(batch[0]["pairs"]) > 1:
                # Preserve progress when one compact response is persistently
                # malformed: retry only that case as independently keyed pairs.
                case = batch[0]
                split_judged = {}
                split_failed = False
                for index, pair in enumerate(case["pairs"]):
                    split_case = {"case_id": f"{case['case_id']}-p{index}",
                                  "query": case["query"], "pairs": [pair]}
                    values, split_diag = self._request_case_batch([split_case])
                    for key in ("request_count", "retry_count", "malformed_count", "latency_seconds",
                                "prompt_tokens", "completion_tokens", "invalid_type_count"):
                        diagnostics[key] += split_diag.get(key, 0)
                    if values is None:
                        split_failed = True
                        break
                    split_judged[(case["case_id"], pair["source"]["evidence_id"],
                                   pair["target"]["evidence_id"])] = next(iter(values.values()))
                if not split_failed and len(split_judged) == len(case["pairs"]):
                    judged = split_judged
                    diagnostics["failed_batch_count"] = 0
            for key in (
                "pair_count", "request_count", "retry_count", "malformed_count", "latency_seconds",
                "prompt_tokens", "completion_tokens", "invalid_type_count", "failed_batch_count",
                "padded_missing_count",
            ):
                totals[key] += diagnostics[key]
            if judged is not None:
                for case in batch:
                    for pair in case["pairs"]:
                        key = (case["case_id"], pair["source"]["evidence_id"], pair["target"]["evidence_id"])
                        self._save_cache(pair["fingerprint"], judged[key])
                        totals["saved_pair_count"] += 1
            print(
                f"relation cache warm: {min(start + len(batch), len(pending))}/{len(pending)} cases",
                flush=True,
            )
            if judged is None:
                break
        return totals

    def judge(self, query: dict, pairs: list[dict]) -> tuple[dict[tuple[str, str], dict], dict]:
        output: dict[tuple[str, str], dict] = {}
        missing = []
        diagnostics = {
            "cache_lookup_count": len(pairs), "cache_hit_count": 0, "llm_called_pair_count": 0,
            "request_count": 0, "retry_count": 0, "malformed_count": 0, "latency_seconds": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "invalid_type_count": 0,
            "client_failure_pair_count": 0,
        }
        for pair in pairs:
            source, target = pair["source"], pair["target"]
            fingerprint = self.fingerprint(query, source, target)
            cached = self._load_cache(fingerprint)
            key = (source["evidence_id"], target["evidence_id"])
            if cached is not None:
                output[key] = cached
                diagnostics["cache_hit_count"] += 1
            else:
                missing.append({**pair, "fingerprint": fingerprint})
        diagnostics["llm_called_pair_count"] = len(missing)
        for start in range(0, len(missing), self.config.batch_size):
            batch = missing[start : start + self.config.batch_size]
            if self.config.case_batch_mode:
                case_id = hashlib.sha256(
                    f"{query['query_text']}\n{query['query_time']}\n{start}".encode("utf-8")
                ).hexdigest()[:16]
                case_judged, batch_diag = self._request_case_batch(
                    [{"case_id": case_id, "query": query, "pairs": batch}]
                )
                if case_judged is None and len(batch) > 1:
                    case_judged = {}
                    for offset, pair in enumerate(batch):
                        split_id = f"{case_id}-{offset:02d}"
                        split, split_diag = self._request_case_batch(
                            [{"case_id": split_id, "query": query, "pairs": [pair]}]
                        )
                        for diag_key in ("request_count", "retry_count", "malformed_count", "latency_seconds",
                                         "prompt_tokens", "completion_tokens", "invalid_type_count",
                                         "padded_missing_count"):
                            batch_diag[diag_key] += split_diag.get(diag_key, 0)
                        if split is None or split_diag.get("padded_missing_count"):
                            case_judged = None
                            break
                        (_, source_id, target_id), value = next(iter(split.items()))
                        case_judged[(case_id, source_id, target_id)] = value
                judged = ({(source, target): value for (_, source, target), value in case_judged.items()}
                          if case_judged is not None and not batch_diag.get("padded_missing_count") else None)
            else:
                judged, batch_diag = self._request_batch(query, batch)
            for key in ("request_count", "retry_count", "malformed_count", "latency_seconds", "prompt_tokens",
                        "completion_tokens", "invalid_type_count"):
                diagnostics[key] += batch_diag[key]
            for pair in batch:
                key = (pair["source"]["evidence_id"], pair["target"]["evidence_id"])
                value = (judged[key] if judged is not None else {
                    "source_id": key[0], "target_id": key[1], "has_edge": False,
                    "relation_type": NO_EDGE, "confidence": 0.0,
                    "reason_code": "client_failure_after_retries",
                })
                output[key] = value
                if value.get("reason_code") != "client_failure_after_retries":
                    self._save_cache(pair["fingerprint"], value)
                else:
                    diagnostics["client_failure_pair_count"] += 1
        return output, diagnostics


class QueryConditionedRelationScorer:
    def __init__(self, client: LLMRelationClient, relation_threshold: float, pair_proposer=None,
                 pair_budget: int = 24):
        self.client = client
        self.config = client.config
        self.relation_threshold = relation_threshold
        self.pair_proposer = pair_proposer
        self.pair_budget = pair_budget

    @staticmethod
    def _clock(document: dict) -> tuple[str, str, str]:
        return document["event_time"], document["available_at"], document["evidence_id"]

    def prefilter(self, candidates: list[dict], node_scores: dict[str, dict],
                  relation_kind: Callable[[dict, dict], tuple[str, float]],
                  similarity: Callable[[str, str], float], mode: str = "stage2a",
                  query: dict | None = None) -> tuple[list[dict], int]:
        if mode in {"learned", "hybrid_learned"}:
            if self.pair_proposer is None or query is None:
                raise ValueError("learned prefilter requires pair_proposer and query")
            raw_count = len(candidates) * (len(candidates) - 1) // 2
            # The deployment-visible role parser remains the frozen pipeline parser.
            from .pipeline import TEFRAGV6
            role_demands = TEFRAGV6._role_demands(query["query_text"])
            proposal_mode = "learned" if mode == "learned" else "hybrid"
            return self.pair_proposer.rank(query, candidates, node_scores, role_demands,
                                           self.pair_budget, proposal_mode), raw_count
        if mode not in {"stage2a", "improved"}:
            raise ValueError("prefilter mode must be stage2a, improved, learned, or hybrid_learned")
        documents = [item["document"] for item in candidates]
        ranked = []
        raw_count = 0
        for source in documents:
            for target in documents:
                if self._clock(source) >= self._clock(target):
                    continue
                raw_count += 1
                same_chain = source.get("chain_id") == target.get("chain_id")
                same_episode = source.get("episode_id") == target.get("episode_id")
                kind, prior = relation_kind(source, target)
                lexical = similarity(source["evidence_id"], target["evidence_id"])
                heuristic = min(1.0, prior * (0.62 + 0.22 * same_chain + 0.08 * same_episode + 0.18 * lexical))
                explicit = target.get("supersedes") == source["evidence_id"]
                compatible = explicit or (
                    same_chain and (
                        heuristic >= self.config.prefilter_heuristic_floor
                        or source.get("event_type") in {"procedure_applicability", "uncertainty", "diagnosis"}
                        or target.get("event_type") in {"diagnosis", "work_order", "correction", "verification", "uncertainty"}
                    )
                )
                if mode == "improved":
                    transition = (
                        source.get("event_type"), target.get("event_type")
                    ) in {
                        ("state_observation", "diagnosis"), ("inspection", "diagnosis"),
                        ("diagnosis", "work_order"), ("diagnosis", "repair"),
                        ("work_order", "verification"), ("repair", "verification"),
                        ("procedure_applicability", "work_order"),
                        ("uncertainty", "verification"), ("uncertainty", "correction"),
                    }
                    top_neighborhood = (
                        node_scores[source["evidence_id"]]["total"] >= 0.65
                        or node_scores[target["evidence_id"]]["total"] >= 0.65
                    )
                    special = source.get("event_type") in {"uncertainty", "correction", "procedure_applicability"} \
                        or target.get("event_type") in {"uncertainty", "correction", "verification"}
                    compatible = compatible or transition or (same_chain and special) or (
                        same_chain and top_neighborhood and lexical >= 0.08
                    )
                if not compatible:
                    continue
                node_prior = (node_scores[source["evidence_id"]]["total"] + node_scores[target["evidence_id"]]["total"]) / 2
                priority = heuristic + 0.12 * node_prior + 0.40 * explicit + 0.05 * same_episode
                ranked.append({
                    "source": source, "target": target, "heuristic_type": kind,
                    "heuristic_confidence": heuristic, "same_chain": same_chain,
                    "same_episode": same_episode, "explicit_supersession": explicit, "priority": priority,
                })
        ranked.sort(key=lambda pair: (-pair["priority"], pair["source"]["evidence_id"], pair["target"]["evidence_id"]))
        limit = self.config.max_pairs_per_query if mode == "stage2a" else max(24, self.config.max_pairs_per_query)
        return ranked[:limit], raw_count

    def score(self, query: dict, candidates: list[dict], node_scores: dict[str, dict],
              relation_kind: Callable[[dict, dict], tuple[str, float]],
              similarity: Callable[[str, str], float], mode: str,
              prefilter_mode: str = "stage2a") -> tuple[list[dict], dict]:
        if mode not in {"llm", "hybrid"}:
            raise ValueError("LLM scorer mode must be llm or hybrid")
        pairs, raw_count = self.prefilter(candidates, node_scores, relation_kind, similarity,
                                          prefilter_mode, query=query)
        deterministic = [pair for pair in pairs if mode == "hybrid" and pair["explicit_supersession"]]
        semantic_pairs = [pair for pair in pairs if pair not in deterministic]
        judgments, diagnostics = self.client.judge(query, semantic_pairs)
        edges = []
        for pair in deterministic:
            edges.append({
                "source_id": pair["source"]["evidence_id"], "target_id": pair["target"]["evidence_id"],
                "relation_type": "supersession", "score": 1.0, "same_chain": pair["same_chain"],
                "same_episode": pair["same_episode"], "relation_source": "deterministic_explicit",
                "reason_code": "explicit_supersedes_metadata",
            })
        llm_no_edge = 0
        for pair in semantic_pairs:
            key = (pair["source"]["evidence_id"], pair["target"]["evidence_id"])
            judgment = judgments[key]
            if not judgment["has_edge"] or judgment["confidence"] < self.config.llm_confidence_threshold:
                llm_no_edge += 1
                continue
            confidence = judgment["confidence"]
            if mode == "hybrid":
                confidence = self.config.hybrid_llm_weight * confidence + (
                    1.0 - self.config.hybrid_llm_weight
                ) * pair["heuristic_confidence"]
            edges.append({
                "source_id": key[0], "target_id": key[1], "relation_type": judgment["relation_type"],
                "score": confidence, "same_chain": pair["same_chain"], "same_episode": pair["same_episode"],
                "relation_source": mode, "reason_code": judgment["reason_code"],
            })
        diagnostics.update({
            "raw_possible_pair_count": raw_count, "prefiltered_pair_count": len(pairs),
            "deterministic_edge_count": len(deterministic), "accepted_edge_count": len(edges),
            "no_edge_count": llm_no_edge,
            "relation_type_counts": dict(Counter(edge["relation_type"] for edge in edges)),
            "prefilter_pairs": [[pair["source"]["evidence_id"], pair["target"]["evidence_id"]] for pair in pairs],
            "prefilter_mode": prefilter_mode,
        })
        return sorted(edges, key=lambda edge: (-edge["score"], edge["source_id"], edge["target_id"])), diagnostics
