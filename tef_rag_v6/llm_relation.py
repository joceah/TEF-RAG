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
                rows = parsed.get("judgments") if isinstance(parsed, dict) else None
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
            "pair_count": len(pairs), "error": last_error,
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
        for case in cases:
            missing = []
            for pair in case["pairs"]:
                fingerprint = self.fingerprint(case["query"], pair["source"], pair["target"])
                if self._load_cache(fingerprint) is not None:
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
            judged, batch_diag = self._request_batch(query, batch)
            for key in ("request_count", "retry_count", "malformed_count", "latency_seconds", "prompt_tokens",
                        "completion_tokens", "invalid_type_count"):
                diagnostics[key] += batch_diag[key]
            for pair in batch:
                key = (pair["source"]["evidence_id"], pair["target"]["evidence_id"])
                value = judged[key]
                output[key] = value
                if value.get("reason_code") != "client_failure_after_retries":
                    self._save_cache(pair["fingerprint"], value)
                else:
                    diagnostics["client_failure_pair_count"] += 1
        return output, diagnostics


class QueryConditionedRelationScorer:
    def __init__(self, client: LLMRelationClient, relation_threshold: float):
        self.client = client
        self.config = client.config
        self.relation_threshold = relation_threshold

    @staticmethod
    def _clock(document: dict) -> tuple[str, str, str]:
        return document["event_time"], document["available_at"], document["evidence_id"]

    def prefilter(self, candidates: list[dict], node_scores: dict[str, dict],
                  relation_kind: Callable[[dict, dict], tuple[str, float]],
                  similarity: Callable[[str, str], float]) -> tuple[list[dict], int]:
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
        return ranked[: self.config.max_pairs_per_query], raw_count

    def score(self, query: dict, candidates: list[dict], node_scores: dict[str, dict],
              relation_kind: Callable[[dict, dict], tuple[str, float]],
              similarity: Callable[[str, str], float], mode: str) -> tuple[list[dict], dict]:
        if mode not in {"llm", "hybrid"}:
            raise ValueError("LLM scorer mode must be llm or hybrid")
        pairs, raw_count = self.prefilter(candidates, node_scores, relation_kind, similarity)
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
        })
        return sorted(edges, key=lambda edge: (-edge["score"], edge["source_id"], edge["target_id"])), diagnostics
