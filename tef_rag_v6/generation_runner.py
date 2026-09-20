"""Frozen TEF-RAG v6 downstream generation runtime.

The generator receives only query text/context and the exact frozen selected
evidence records, up to the Top-5 budget. Method-specific scores/relations and
generation gold are hidden.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PUBLIC = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/public"
GEN_META = ROOT / "data/generated/tef_v6_generation_gold_v1/metadata"
OUT = ROOT / "results/v6/generation_eval_v1_9_exact_duplicate_suffix"
PRED_OUT = OUT / "predictions"
CACHE = ROOT / ".cache/tef_rag_v6_generation_eval_v1_9_exact_duplicate_suffix"
RETRIEVAL_ROOT = ROOT / "results/v6/sealed_test/predictions"
RETRIEVAL_MANIFEST = ROOT / "results/v6/sealed_test/prediction_manifest.json"
DEFAULT_PRIVATE = Path(os.environ.get("TEF_GENERATION_PRIVATE_ROOT", str(ROOT.parent / ".tef_v6_generation_gold_private")))
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")
MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
TEMPERATURE = 0.0
MAX_TOKENS = 5000
THINKING_MODE = "disabled"
CALL_INTERVAL = 1.2
PROMPT_VERSION = "tef-v6-generation-eval-v1.3"
GENERATION_PROTOCOL_VERSION = "v1.9-exact-duplicate-root-field-suffix"
EXACT_DUPLICATE_ROOT_FIELD_SUFFIX_NORMALIZATION_VERSION = "exact-duplicate-root-field-suffix-v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_time(value: str):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def read_env() -> dict[str, str]:
    candidates = [
        ROOT / "local.env",
        ROOT.parent / "local.env",
        ROOT.parent.parent / "local.env",
        Path(r"D:\electric-project\local.env"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        values: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
                key, value = raw.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
        if values.get("API_KEY"):
            return values
    raise RuntimeError("local.env with API_KEY not found")


def schema() -> dict[str, Any]:
    return read_json(GEN_META / "schema.json")


def aliases() -> dict[str, Any]:
    return read_json(GEN_META / "alias_registry.json")


def parameters() -> dict[str, Any]:
    return read_json(GEN_META / "parameter_registry.json")


def queries() -> list[dict[str, Any]]:
    rows = read_jsonl(PUBLIC / "queries_test.jsonl")
    if len(rows) != 480 or len({row["query_id"] for row in rows}) != 480:
        raise RuntimeError("expected 480 unique public test queries")
    return rows


def evidence_map() -> dict[str, dict[str, Any]]:
    rows = read_jsonl(PUBLIC / "evidence.jsonl")
    return {row["evidence_id"]: row for row in rows}


def retrieval_paths() -> dict[str, Path]:
    return {method: RETRIEVAL_ROOT / f"{method}.json" for method in METHODS}


def retrieval_predictions() -> dict[str, list[dict[str, Any]]]:
    return {method: read_json(path) for method, path in retrieval_paths().items()}


def public_evidence(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "evidence_id", "text", "event_time", "available_at", "asset_id", "asset_model",
        "event_type", "source_type", "episode_id", "procedure_version", "valid_from",
        "valid_to", "withdrawn_at", "model_scope", "supersedes", "supersedes_evidence_id",
    )
    return {key: row[key] for key in allowed if key in row}


def visible_at(row: dict[str, Any], query: dict[str, Any]) -> bool:
    cutoff = parse_time(query["query_time"])
    if parse_time(row["event_time"]) > cutoff or parse_time(row["available_at"]) > cutoff:
        return False
    is_proc = row.get("event_type") == "procedure_applicability" or row.get("source_type") == "procedure"
    if is_proc:
        if row.get("valid_from") and cutoff < parse_time(row["valid_from"]):
            return False
        if row.get("valid_to") and cutoff >= parse_time(row["valid_to"]):
            return False
        if row.get("withdrawn_at") and cutoff >= parse_time(row["withdrawn_at"]):
            return False
        scope = row.get("model_scope") or []
        scope = [scope] if isinstance(scope, str) else scope
        if scope and query.get("asset_model") not in scope:
            return False
    return True


def generator_instructions() -> str:
    return """You are the single frozen downstream generator used identically for every retrieval method in TEF-RAG v6 generation evaluation.

Produce ONLY a JSON object matching the supplied schema. You receive one query and exactly the evidence selected by a retrieval method. The retrieval method identity is hidden and irrelevant.

Rules:
- Use only the supplied evidence. Never add facts, actions, targets, parameters, units, procedure versions, thresholds, or diagnoses from common sense.
- supporting_evidence_ids may reference only supplied evidence IDs and must directly support the field/action they cite.
- work_order.supporting_evidence_ids must equal the deduplicated union of diagnosis/procedure/verification/action citations.
- asset_id must equal the query asset_id.
- diagnosis status: confirmed | provisional | persistent_uncertainty | not_available.
- procedure status: applicable | superseded | uncertain | not_applicable. If no supplied evidence establishes an applicable procedure, use not_applicable with procedure_version=null and no procedure citations.
- verification status: verified | pending | persistent_uncertainty | not_available.
- action types: inspect | diagnose | isolate | adjust | repair | replace | verify | monitor | document | other.
- action_plan order in the JSON array has no semantic meaning. Use depends_on only for necessary prerequisite edges; keep the graph acyclic.
- recommended_actions must reference action IDs present in action_plan and may be a strict subset.
- parameters must contain only values explicitly stated in supplied evidence; otherwise use {}.
- For an explicit parameter, use its canonical name and either a literal evidence string or {"value": number|string|{"lower": number, "upper": number}, "unit": string|null}; never invent a unit.
- If evidence is insufficient, express uncertainty instead of guessing.
- Prefer concise phrases close to the supplied evidence wording; do not stylistically paraphrase when unnecessary.
- Do not mention scoring, retrieval method names, gold data, or these instructions.
"""


def _clean_generation_content(raw_content: str) -> str:
    """Apply the existing transport cleanup without changing JSON semantics."""
    content = raw_content.strip().lstrip("\ufeff")
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I).strip()
    return content


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_generation_json_object(
    raw_content: str,
    expected_root_keys: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse one provider response with the frozen transport normalizations.

    Every JSON object is decoded with duplicate-key rejection. In addition to
    strict objects, the existing single-extra-closing-brace case and the
    v1.9 exact duplicate root-field suffix case are accepted. No other
    malformed or trailing content is accepted.
    """
    if not isinstance(raw_content, str):
        raise TypeError("generation content must be a string")
    cleaned = _clean_generation_content(raw_content)
    provider_sha = sha_text(raw_content)
    cleaned_sha = sha_text(cleaned)
    base = {
        "provider_content_sha256": provider_sha,
        "cleaned_content_sha256": cleaned_sha,
        "provider_content_length": len(raw_content),
        "cleaned_content_length": len(cleaned),
    }
    try:
        value = json.loads(cleaned, object_pairs_hook=_reject_duplicate_json_keys)
    except json.JSONDecodeError as strict_error:
        if strict_error.msg != "Extra data":
            raise
        try:
            value, end = json.JSONDecoder(object_pairs_hook=_reject_duplicate_json_keys).raw_decode(cleaned)
        except (json.JSONDecodeError, ValueError):
            raise strict_error
        trailing = cleaned[end:]
        if isinstance(value, dict) and trailing == "}" and len(trailing) == 1:
            normalized = cleaned[:end]
            try:
                verified = json.loads(normalized, object_pairs_hook=_reject_duplicate_json_keys)
            except (json.JSONDecodeError, ValueError):
                raise strict_error
            if not isinstance(verified, dict) or verified != value:
                raise strict_error
            provenance = {
                **base,
                "parse_mode": "single_extra_closing_brace",
                "accepted_json_text_sha256": sha_text(normalized),
                "accepted_json_text_length": len(normalized),
                "normalization_removed_chars": 1,
            }
            return verified, provenance

        output_schema = schema()
        properties = output_schema.get("properties") if isinstance(output_schema, dict) else None
        declared_root_keys = set(properties) if isinstance(properties, dict) else set()
        root_keys = declared_root_keys if expected_root_keys is None else set(expected_root_keys) & declared_root_keys
        if isinstance(value, dict) and end > 0 and cleaned[end - 1] == "}":
            trailing_core = trailing.rstrip(" \t\r\n")
            if trailing_core.startswith(",") and trailing_core.endswith("}"):
                decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_json_keys)
                try:
                    duplicate_root_key, key_end = decoder.raw_decode(trailing_core, 1)
                    if not isinstance(duplicate_root_key, str) or key_end >= len(trailing_core) or trailing_core[key_end] != ":":
                        raise ValueError("invalid duplicate root-field suffix")
                    duplicate_value, value_end = decoder.raw_decode(trailing_core, key_end + 1)
                    if value_end != len(trailing_core) - 1 or trailing_core[value_end] != "}":
                        raise ValueError("duplicate root-field suffix has trailing content")
                except (json.JSONDecodeError, ValueError):
                    raise strict_error
                if duplicate_root_key not in root_keys or duplicate_root_key not in value:
                    raise strict_error
                original_value = value[duplicate_root_key]
                original_canonical = _canonical_json(original_value)
                duplicate_canonical = _canonical_json(duplicate_value)
                if duplicate_value != original_value or duplicate_canonical != original_canonical:
                    raise strict_error
                provenance = {
                    **base,
                    "parse_mode": "exact_duplicate_root_field_suffix",
                    "accepted_json_text_sha256": sha_text(cleaned[:end]),
                    "accepted_json_text_length": end,
                    "normalization_removed_chars": len(trailing),
                    "original_json_decode_error_msg": strict_error.msg,
                    "original_json_decode_error_pos": strict_error.pos,
                    "duplicated_root_key": duplicate_root_key,
                    "duplicate_suffix_sha256": sha_text(trailing),
                    "original_field_canonical_sha256": sha_text(original_canonical),
                    "duplicate_field_canonical_sha256": sha_text(duplicate_canonical),
                    "duplicate_values_equal": True,
                    "duplicate_suffix_char_length": len(trailing),
                    "normalization_version": EXACT_DUPLICATE_ROOT_FIELD_SUFFIX_NORMALIZATION_VERSION,
                }
                return value, provenance
        raise strict_error
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    provenance = {
        **base,
        "parse_mode": "strict",
        "accepted_json_text_sha256": cleaned_sha,
        "accepted_json_text_length": len(cleaned),
        "normalization_removed_chars": 0,
    }
    return value, provenance


def validate_parse_provenance(value: Any) -> list[str]:
    """Validate the non-content provenance persisted with a prediction row/cache."""
    if not isinstance(value, dict):
        return ["parse provenance must be an object"]
    errors: list[str] = []
    mode = value.get("parse_mode")
    if mode not in {"strict", "single_extra_closing_brace", "exact_duplicate_root_field_suffix"}:
        errors.append("parse_mode is invalid")
    for key in ("provider_content_sha256", "cleaned_content_sha256", "accepted_json_text_sha256"):
        digest = value.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append(f"{key} is invalid")
    for key in ("provider_content_length", "cleaned_content_length", "accepted_json_text_length", "normalization_removed_chars"):
        number = value.get(key)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            errors.append(f"{key} is invalid")
    if not errors:
        if value["provider_content_length"] < value["cleaned_content_length"]:
            errors.append("provider content length is shorter than cleaned content")
        if mode == "strict":
            if value["normalization_removed_chars"] != 0:
                errors.append("strict parse removed characters")
            if value["accepted_json_text_sha256"] != value["cleaned_content_sha256"]:
                errors.append("strict parse accepted hash differs from cleaned hash")
            if value["accepted_json_text_length"] != value["cleaned_content_length"]:
                errors.append("strict parse accepted length differs from cleaned length")
        elif mode == "single_extra_closing_brace":
            if value["normalization_removed_chars"] != 1:
                errors.append("normalized parse must remove exactly one character")
            if value["accepted_json_text_length"] != value["cleaned_content_length"] - 1:
                errors.append("normalized parse accepted length is invalid")
        elif mode == "exact_duplicate_root_field_suffix":
            suffix_length = value.get("duplicate_suffix_char_length")
            if not isinstance(suffix_length, int) or isinstance(suffix_length, bool) or suffix_length <= 0:
                errors.append("duplicate suffix length is invalid")
            elif value["normalization_removed_chars"] != suffix_length:
                errors.append("duplicate suffix removal length is invalid")
            elif value["accepted_json_text_length"] + suffix_length != value["cleaned_content_length"]:
                errors.append("duplicate suffix accepted length is invalid")
            if value.get("normalization_version") != EXACT_DUPLICATE_ROOT_FIELD_SUFFIX_NORMALIZATION_VERSION:
                errors.append("duplicate suffix normalization version is invalid")
            if value.get("original_json_decode_error_msg") != "Extra data":
                errors.append("original JSON decode message is invalid")
            error_pos = value.get("original_json_decode_error_pos")
            if not isinstance(error_pos, int) or isinstance(error_pos, bool) or error_pos < 0:
                errors.append("original JSON decode position is invalid")
            if not isinstance(value.get("duplicated_root_key"), str) or not value["duplicated_root_key"]:
                errors.append("duplicated root key is invalid")
            if value.get("duplicate_values_equal") is not True:
                errors.append("duplicate values equality marker is invalid")
            for key in ("duplicate_suffix_sha256", "original_field_canonical_sha256", "duplicate_field_canonical_sha256"):
                digest = value.get(key)
                if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                    errors.append(f"{key} is invalid")
    return errors


def build_prompt(query: dict[str, Any], selected: list[dict[str, Any]], output_schema: dict[str, Any]) -> tuple[str, str]:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "query": {
            key: query.get(key)
            for key in ("query_id", "query_text", "query_time", "asset_id", "asset_model", "asset_context")
            if key in query
        },
        "selected_evidence": [public_evidence(row) for row in selected],
        "output_schema": output_schema,
    }
    return generator_instructions(), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class DeepSeekClient:
    def __init__(self, cache_dir: Path, official: bool = False, diagnostic_dir: Path | None = None):
        env = read_env()
        self.endpoint = env.get("ENDPOINT", BASE_URL.rstrip("/") + "/chat/completions")
        if official and self.endpoint != BASE_URL.rstrip("/") + "/chat/completions":
            raise RuntimeError("formal generation requires the official DeepSeek endpoint")
        self.key = env["API_KEY"]
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostic_dir = diagnostic_dir
        if self.diagnostic_dir is not None:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostic_events: list[dict[str, Any]] = []
        self.last_call = 0.0
        self.last_request_hash: str | None = None
        self.last_parse_provenance: dict[str, Any] | None = None
        self.stats = {
            "requests": 0, "cache_hits": 0, "retries": 0, "failures": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "reasoning_tokens": 0,
        }

    def _record_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                self.stats[key] += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                continue
        details = usage.get("completion_tokens_details")
        reasoning = usage.get("reasoning_tokens")
        if reasoning is None and isinstance(details, dict):
            reasoning = details.get("reasoning_tokens")
        try:
            self.stats["reasoning_tokens"] += int(reasoning or 0)
        except (TypeError, ValueError):
            pass

    @staticmethod
    def _diagnostic_excerpt(text: str, position: int | None = None) -> dict[str, Any]:
        excerpt: dict[str, Any] = {
            "first_300": text[:300],
            "last_300": text[-300:] if text else "",
        }
        if position is not None:
            start = max(0, position - 200)
            excerpt["around_error"] = text[start:min(len(text), position + 200)]
            excerpt["around_error_start"] = start
        return excerpt

    def _write_diagnostic_failure(
        self,
        logical_key: str,
        request_hash: str,
        attempt: int,
        layer: str,
        exc: BaseException,
        *,
        raw_body: bytes | None = None,
        response_status: int | None = None,
        response_headers: dict[str, Any] | None = None,
        envelope: dict[str, Any] | None = None,
        finish_reason: Any = None,
        content: str | None = None,
        parser_mode: str | None = None,
    ) -> None:
        if self.diagnostic_dir is None:
            return
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", logical_key).strip("_") or request_hash
        stem = f"{safe_key}_attempt{attempt + 1}"
        headers = {
            str(key): str(value).replace(self.key, "<API_KEY_REDACTED>")
            for key, value in (response_headers or {}).items()
        }
        event: dict[str, Any] = {
            "logical_key": logical_key,
            "request_fingerprint": request_hash,
            "attempt": attempt + 1,
            "layer": layer,
            "exception": {
                "type": type(exc).__name__,
                "message": str(exc),
                "repr": repr(exc),
            },
            "http_status": response_status,
            "content_type": headers.get("Content-Type"),
            "response_headers": headers,
            "response_id": envelope.get("id") if isinstance(envelope, dict) else None,
            "response_model": envelope.get("model") if isinstance(envelope, dict) else None,
            "finish_reason": finish_reason,
            "usage": envelope.get("usage") if isinstance(envelope, dict) else None,
            "streaming": False,
            "parser_mode_attempted": parser_mode,
            "raw_response_from_cache": False,
        }
        if isinstance(exc, json.JSONDecodeError):
            event["json_decode_error"] = {
                "msg": exc.msg,
                "lineno": exc.lineno,
                "colno": exc.colno,
                "pos": exc.pos,
            }
        if raw_body is not None:
            raw_text = raw_body.decode("utf-8", errors="replace").replace(self.key, "<API_KEY_REDACTED>")
            lower = raw_text.lstrip().lower()
            appearance = "empty" if not raw_text else "json_or_unknown"
            if lower.startswith("<html") or "<html" in lower[:200]:
                appearance = "html"
            elif lower.startswith("event:") or "\nevent:" in lower[:200]:
                appearance = "sse"
            elif not lower.startswith(("{", "[")):
                appearance = "plaintext_or_unknown"
            event["raw_body_byte_length"] = len(raw_body)
            event["raw_body_char_length"] = len(raw_text)
            event["raw_body_sha256"] = hashlib.sha256(raw_body).hexdigest()
            event["raw_body_appearance"] = appearance
            event["raw_body_excerpt"] = self._diagnostic_excerpt(
                raw_text,
                exc.pos if isinstance(exc, json.JSONDecodeError) else None,
            )
            raw_path = self.diagnostic_dir / f"{stem}_raw_response.txt"
            raw_path.write_text(raw_text, encoding="utf-8")
            event["raw_response_path"] = str(raw_path)
        if content is not None:
            safe_content = content.replace(self.key, "<API_KEY_REDACTED>")
            event["content_char_length"] = len(safe_content)
            event["content_byte_length"] = len(safe_content.encode("utf-8"))
            event["content_sha256"] = sha_text(content)
            event["redacted_content_sha256"] = sha_text(safe_content)
            event["content_empty"] = not bool(safe_content)
            event["content_excerpt"] = self._diagnostic_excerpt(
                safe_content,
                exc.pos if isinstance(exc, json.JSONDecodeError) else None,
            )
            content_path = self.diagnostic_dir / f"{stem}_assistant_content.txt"
            content_path.write_text(safe_content, encoding="utf-8")
            event["assistant_content_path"] = str(content_path)
        traceback_path = self.diagnostic_dir / f"{stem}_traceback.txt"
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        traceback_path.write_text(traceback_text.replace(self.key, "<API_KEY_REDACTED>"), encoding="utf-8")
        event["traceback_path"] = str(traceback_path)
        event_path = self.diagnostic_dir / f"{stem}_failure.json"
        event["diagnostic_path"] = str(event_path)
        event_path.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.diagnostic_events.append(event)

    def call(self, system: str, user: str, logical_key: str) -> dict[str, Any]:
        payload = request_payload(system, user)
        request_hash = request_fingerprint(self.endpoint, system, user)
        self.last_request_hash = request_hash
        self.last_parse_provenance = None
        cache_path = self.cache_dir / f"{request_hash}.json"
        if cache_path.exists():
            cached = read_json(cache_path)
            parse_provenance = cached.get("parse_provenance")
            provenance_errors = validate_parse_provenance(parse_provenance)
            if provenance_errors:
                raise RuntimeError("generation cache entry has invalid parse provenance: " + "; ".join(provenance_errors))
            self.stats["cache_hits"] += 1
            self.last_parse_provenance = parse_provenance
            return cached["result"]
        wait = CALL_INTERVAL - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            self.last_call = time.monotonic()
            self.stats["requests"] += 1
            raw_body: bytes | None = None
            response_status: int | None = None
            response_headers: dict[str, Any] = {}
            try:
                req = urllib.request.Request(
                    self.endpoint,
                    data=raw,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
                )
                with urllib.request.urlopen(req, timeout=240) as response:
                    response_status = getattr(response, "status", None)
                    response_headers_obj = getattr(response, "headers", None)
                    response_headers = (
                        dict(response_headers_obj)
                        if response_headers_obj is not None
                        else {}
                    )
                    raw_body = response.read()
                    try:
                        data = json.loads(raw_body.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        self._write_diagnostic_failure(
                            logical_key,
                            request_hash,
                            attempt,
                            "http_response_json",
                            exc,
                            raw_body=raw_body,
                            response_status=response_status,
                            response_headers=response_headers,
                            parser_mode="http_envelope_json",
                        )
                        raise
                if not isinstance(data, dict):
                    raise ValueError("JSON response envelope must be an object")
                usage = data.get("usage") or {}
                self._record_usage(usage)
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("response choices envelope is invalid")
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("incomplete generation: finish_reason=length")
                message = choice.get("message")
                if not isinstance(message, dict):
                    raise ValueError("response message envelope is invalid")
                content = str(message.get("content", ""))
                try:
                    result, parse_provenance = parse_generation_json_object(content)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    self._write_diagnostic_failure(
                        logical_key,
                        request_hash,
                        attempt,
                        "assistant_content_json",
                        exc,
                        raw_body=raw_body,
                        response_status=response_status,
                        response_headers=response_headers,
                        envelope=data,
                        finish_reason=choice.get("finish_reason"),
                        content=content,
                        parser_mode="strict_then_transport_normalizations",
                    )
                    raise
                self.last_parse_provenance = parse_provenance
                write_json(cache_path, {
                    "logical_key": logical_key,
                    "request_hash": request_hash,
                    "usage": usage,
                    "parse_provenance": parse_provenance,
                    "result": result,
                })
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 402, 403) or attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                if attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek generation failure: {type(exc).__name__}") from exc
            self.stats["retries"] += 1
            time.sleep(CALL_INTERVAL * (attempt + 1))
        raise RuntimeError("unreachable")


def request_payload(system: str, user: str) -> dict[str, Any]:
    return {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "thinking": {"type": THINKING_MODE},
    }


def request_fingerprint(endpoint: str, system: str, user: str) -> str:
    return sha_text(json.dumps(
        {"endpoint": endpoint, "payload": request_payload(system, user)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ))


def repair_prompt(
    query: dict[str, Any],
    selected: list[dict[str, Any]],
    bad: dict[str, Any],
    errors: list[str],
    output_schema: dict[str, Any],
) -> tuple[str, str]:
    system = generator_instructions() + "\nThis is the single allowed structural/evidence-grounding repair. Correct only the listed validation failures."
    user = json.dumps({
        "query": {
            key: query.get(key)
            for key in ("query_id", "query_text", "query_time", "asset_id", "asset_model", "asset_context")
            if key in query
        },
        "selected_evidence": [public_evidence(row) for row in selected],
        "previous_output": bad,
        "validation_errors": errors,
        "output_schema": output_schema,
    }, ensure_ascii=False, separators=(",", ":"))
    return system, user
