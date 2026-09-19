"""Frozen TEF-RAG v6 downstream generation runtime.

The generator receives only query text/context and the five selected evidence
records. Method-specific scores/relations and generation gold are hidden.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PUBLIC = ROOT / "data/generated/tef_v6_temporal_hard_benchmark_v1/public"
GEN_META = ROOT / "data/generated/tef_v6_generation_gold_v1/metadata"
OUT = ROOT / "results/v6/generation_eval_v1"
PRED_OUT = OUT / "predictions"
CACHE = ROOT / ".cache/tef_rag_v6_generation_eval_v1"
RETRIEVAL_ROOT = ROOT / "results/v6/sealed_test/predictions"
RETRIEVAL_MANIFEST = ROOT / "results/v6/sealed_test/prediction_manifest.json"
DEFAULT_PRIVATE = Path(os.environ.get("TEF_GENERATION_PRIVATE_ROOT", str(ROOT.parent / ".tef_v6_generation_gold_private")))
METHODS = ("bm25", "bge_reranker", "temporal_bm25", "ta_rag", "tef_rag_stage3d")
MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"
TEMPERATURE = 0.0
MAX_TOKENS = 5000
CALL_INTERVAL = 1.2
PROMPT_VERSION = "tef-v6-generation-eval-v1"
GENERATION_PROTOCOL_VERSION = "v1.2-strict-text"


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
- If evidence is insufficient, express uncertainty instead of guessing.
- Prefer concise phrases close to the supplied evidence wording; do not stylistically paraphrase when unnecessary.
- Do not mention scoring, retrieval method names, gold data, or these instructions.
"""


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
    def __init__(self, cache_dir: Path):
        env = read_env()
        self.key = env["API_KEY"]
        self.endpoint = env.get("ENDPOINT", BASE_URL.rstrip("/") + "/chat/completions")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_call = 0.0
        self.stats = {
            "requests": 0, "cache_hits": 0, "retries": 0, "failures": 0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }

    def call(self, system: str, user: str, logical_key: str) -> dict[str, Any]:
        payload = {
            "model": MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
        }
        request_hash = sha_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        cache_path = self.cache_dir / f"{request_hash}.json"
        if cache_path.exists():
            self.stats["cache_hits"] += 1
            return read_json(cache_path)["result"]
        wait = CALL_INTERVAL - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            self.last_call = time.monotonic()
            self.stats["requests"] += 1
            try:
                req = urllib.request.Request(
                    self.endpoint,
                    data=raw,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
                )
                with urllib.request.urlopen(req, timeout=240) as response:
                    data = json.load(response)
                content = str(data["choices"][0]["message"].get("content", "")).strip().lstrip("\ufeff")
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I).strip()
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError("JSON object required")
                usage = data.get("usage") or {}
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    self.stats[key] += int(usage.get(key) or 0)
                write_json(cache_path, {
                    "logical_key": logical_key,
                    "request_hash": request_hash,
                    "usage": usage,
                    "result": result,
                })
                return result
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 402, 403) or attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                if attempt == 2:
                    self.stats["failures"] += 1
                    raise RuntimeError(f"DeepSeek generation failure: {type(exc).__name__}") from None
            self.stats["retries"] += 1
            time.sleep(CALL_INTERVAL * (attempt + 1))
        raise RuntimeError("unreachable")


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
