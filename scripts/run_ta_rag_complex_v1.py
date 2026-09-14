"""Run the pinned TA-RAG pipeline on all frozen v8 snapshots without gold."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SRC = ROOT / "experiments/runtime/ta_rag_v1/experiment/src"
COMPAT = ROOT / "experiments/compat/ta_rag_v1"
TA_DEPS = ROOT / "experiments/runtime/ta_rag_v1_deps"
TG_DEPS = ROOT / "experiments/runtime/tg_rag_v1_deps"
sys.path[:0] = [str(COMPAT), str(OFFICIAL_SRC), str(ROOT), str(ROOT / "src"), str(ROOT / ".deps")]
sys.path.extend([str(TA_DEPS), str(TG_DEPS)])

import faiss
import build_ta_rag_index as ta_build
import ta_rag_full as ta_query
from scripts.research_llm_transport_v1 import settings


INPUT = ROOT / "experiments/runs/ta_tg_input_complex_v1"
FREEZE = ROOT / "experiments/analyses/tef_complex_dev_candidate_v8/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_TA_TG复杂链开发对比_v1_预登记.md"
RUN = ROOT / "experiments/runs/ta_rag_complex_v1"
OFFICIAL_COMMIT = "9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def official_llm_client_class():
    package_name = "ta_rag_official_tools_complex"
    package = types.ModuleType(package_name)
    package.__path__ = [str(OFFICIAL_SRC / "tools")]
    sys.modules[package_name] = package
    return importlib.import_module(f"{package_name}.llm_response").LLMClient


class CountingCompletions:
    def __init__(self, delegate, trace):
        self.delegate = delegate
        self.trace = trace

    def create(self, **kwargs):
        response = self.delegate.create(**kwargs)
        usage = getattr(response, "usage", None)
        self.trace.append(
            {
                "model": kwargs.get("model"),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        )
        content = response.choices[0].message.content or ""
        if "``json" not in content:
            response.choices[0].message.content = "``json\n" + content + "\n```"
        return response


class CapturingTemporalClient:
    def __init__(self, delegate):
        self.delegate = delegate
        self.parsed = None

    def temporal_process_sentence(self, text, chance=20):
        self.parsed = self.delegate.temporal_process_sentence(text, chance=min(chance, 2))
        return self.parsed


def configured_parser(trace):
    cfg = settings()
    suffix = "/chat/completions"
    base_url = cfg["endpoint"][: -len(suffix)] if cfg["endpoint"].endswith(suffix) else cfg["endpoint"]
    client = official_llm_client_class()(llm_base_url=base_url, llm_api_key=cfg["key"], model=cfg["model"])
    real = client.openai_client
    client.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=CountingCompletions(real.chat.completions, trace))
    )
    return CapturingTemporalClient(client)


def main():
    if not FREEZE.exists() or not (INPUT / "manifest.json").exists():
        raise RuntimeError("frozen data and prepared snapshots required")
    if (RUN / "completion.json").exists():
        raise RuntimeError("refusing to overwrite completed TA-RAG run")
    RUN.mkdir(parents=True, exist_ok=True)
    output_dir = RUN / "queries"
    output_dir.mkdir(exist_ok=True)
    queries = lines(INPUT / "queries.jsonl")
    by_snapshot = {}
    for query in queries:
        by_snapshot.setdefault(query["snapshot_key"], []).append(query)
    for snapshot_key, snapshot_queries in sorted(by_snapshot.items()):
        corpus_path = INPUT / "snapshots" / snapshot_key / "ta_corpus.json"
        rows = read(corpus_path)
        index = ta_build.create_faiss_flat_index(384, faiss.METRIC_INNER_PRODUCT)
        index, metadata, interval_index = ta_build.load_embed_and_build_indices_for_tarag(rows, index)
        for query in snapshot_queries:
            output_path = output_dir / f"{query['query_id']}.json"
            if output_path.exists():
                continue
            question = query["text"].split("；", 1)[-1]
            trace = []
            parser = configured_parser(trace)
            ta_query.LLM_CLIENT_A = parser
            ranked, total, semantic, temporal, embedding = ta_query.ta_rag_retrieval(
                question, index, metadata, interval_index, top_k=5
            )
            result = {
                "method": "TA-RAG pinned official downstream retrieval with disclosed CPU adapters",
                "official_commit": OFFICIAL_COMMIT,
                "query_id": query["query_id"],
                "snapshot_key": snapshot_key,
                "question_sent_to_model": question,
                "temporal_parse": parser.parsed,
                "evidence_ids": [item["corpus_uid"] for item in ranked],
                "candidate_count": len(rows),
                "gold_read": False,
                "llm_requests": trace,
                "timing_seconds": {
                    "total": total,
                    "semantic": semantic,
                    "temporal_parser": temporal,
                    "embedding": embedding,
                },
            }
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"TA-RAG {query['query_id']}: {len(result['evidence_ids'])} records, {len(trace)} request(s)", flush=True)
    saved = [read(path) for path in sorted(output_dir.glob("*.json"))]
    if len(saved) != len(queries):
        raise RuntimeError(f"incomplete TA-RAG run: {len(saved)}/{len(queries)}")
    usage = {
        "requests": sum(len(row["llm_requests"]) for row in saved),
        "prompt_tokens": sum((call.get("prompt_tokens") or 0) for row in saved for call in row["llm_requests"]),
        "completion_tokens": sum((call.get("completion_tokens") or 0) for row in saved for call in row["llm_requests"]),
        "total_tokens": sum((call.get("total_tokens") or 0) for row in saved for call in row["llm_requests"]),
    }
    inputs = [Path(__file__).resolve(), INPUT / "manifest.json", INPUT / "queries.jsonl", FREEZE, PLAN]
    completion = {
        "queries": len(saved),
        "snapshots": len(by_snapshot),
        "top_k": 5,
        "official_commit": OFFICIAL_COMMIT,
        "gold_read": False,
        "authoring_read": False,
        "usage": usage,
        "compatibility": {
            "query_parser": "official prompt/validator/retry loop; bare JSON fence compatibility",
            "embedding": "shared local multilingual MiniLM 384d",
            "interval_index": "linear NCLS API-compatible overlap implementation",
            "vector_index": "exact NumPy inner-product flat index",
        },
        "input_hashes": {str(path.relative_to(ROOT)): sha(path) for path in inputs},
        "query_output_hashes": {path.name: sha(path) for path in sorted(output_dir.glob("*.json"))},
    }
    (RUN / "completion.json").write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(saved), "usage": usage}, ensure_ascii=False))


if __name__ == "__main__":
    main()
