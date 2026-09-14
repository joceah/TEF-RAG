"""Build/query one frozen snapshot with pinned TG-RAG, resumably and gold-free."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "experiments/compat/tg_rag_v1"),
    str(ROOT / "experiments/runtime/tg_rag_v1"),
    str(ROOT),
    str(ROOT / "src"),
    str(ROOT / ".deps"),
]
sys.path.append(str(ROOT / "experiments/runtime/tg_rag_v1_deps"))

from baseline_adapters.query_text_v2 import semantic_question
from baseline_adapters.tg_rag_source_v2 import source_ids
from scripts.research_llm_transport_v1 import settings
from scripts.temporal_retrieval_eval_v1_lib import Encoder
from source_id import source_id_restoring_storage
from tgrag import QueryParam, TemporalGraphRAG
from tgrag.src.build import create_llm_function
from tgrag.src.core import building
from tgrag.src.storage.graph_networkx import NetworkXStorage
from tgrag.src.utils.types import EmbeddingFunc


INPUT = ROOT / "experiments/runs/ta_tg_input_complex_v1"
FREEZE = ROOT / "experiments/analyses/tef_complex_dev_candidate_v8/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_TA_TG复杂链开发对比_v1_预登记.md"
SUPPLEMENT = ROOT / "plans/TG_RAG复杂链领域适配_v1_补充.md"
SOURCE_SUPPLEMENT = ROOT / "plans/TG_RAG来源恢复_v2_补充.md"
TEXT_PLAN = ROOT / "plans/复杂链知识截止文本规范化_v2_补充.md"
ADAPTER = ROOT / "baseline_adapters/query_text_v2.py"
SOURCE_ADAPTER = ROOT / "baseline_adapters/tg_rag_source_v2.py"
RUN = ROOT / "experiments/runs/tg_rag_complex_v2"
OFFICIAL_COMMIT = "58a57e0bc173064fa0ad7ccf595cf6e266523619"
ENTITY_TYPES = ["equipment", "component", "fault", "symptom", "action", "test", "result", "procedure", "work_order"]
SourceIdRestoringNetworkXStorage = source_id_restoring_storage(NetworkXStorage)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def graph_instance(graph_dir, encoder):
    cfg = settings()
    suffix = "/chat/completions"
    base_url = cfg["endpoint"][: -len(suffix)] if cfg["endpoint"].endswith(suffix) else cfg["endpoint"]
    llm = create_llm_function("openai", cfg["model"], api_key=cfg["key"], base_url=base_url)

    async def local_embedding(texts):
        return encoder.encode(list(texts))

    building._get_prompts()["DEFAULT_ENTITY_TYPES"] = ENTITY_TYPES
    return TemporalGraphRAG(
        working_dir=str(graph_dir),
        embedding_func=EmbeddingFunc(embedding_dim=384, max_token_size=128, func=local_embedding),
        best_model_func=llm,
        cheap_model_func=llm,
        graph_storage_cls=SourceIdRestoringNetworkXStorage,
        best_model_max_async=3,
        cheap_model_max_async=3,
        embedding_func_max_async=1,
    )


def run_snapshot(snapshot_key):
    mapping = read(INPUT / "snapshot_mapping.json")
    if snapshot_key not in mapping:
        raise RuntimeError(f"unknown snapshot: {snapshot_key}")
    visible = set(mapping[snapshot_key]["visible_record_ids"])
    snapshot_input = INPUT / "snapshots" / snapshot_key
    snapshot_run = RUN / "snapshots" / snapshot_key
    graph_dir = snapshot_run / "graph"
    graph_complete = snapshot_run / "graph_complete.json"
    completion_path = snapshot_run / "completion.json"
    if completion_path.exists():
        print(f"TG-RAG snapshot already complete: {snapshot_key}")
        return
    if graph_dir.exists() and any(graph_dir.iterdir()) and not graph_complete.exists():
        raise RuntimeError(f"partial graph preserved; choose a new run version: {graph_dir}")
    snapshot_run.mkdir(parents=True, exist_ok=True)
    encoder = Encoder()
    graph = graph_instance(graph_dir, encoder)
    corpus_paths = sorted((snapshot_input / "tg_corpus").glob("*.txt"))
    if not graph_complete.exists():
        documents = [{"title": path.stem, "doc": path.read_text(encoding="utf-8")} for path in corpus_paths]
        graph.insert(documents)
        graph_complete.write_text(
            json.dumps(
                {
                    "snapshot_key": snapshot_key,
                    "documents": len(documents),
                    "input_hashes": {path.name: sha(path) for path in corpus_paths},
                    "entity_types": ENTITY_TYPES,
                    "gold_read": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    output_dir = snapshot_run / "queries"
    output_dir.mkdir(exist_ok=True)
    queries = [row for row in lines(INPUT / "queries.jsonl") if row["snapshot_key"] == snapshot_key]
    for query in queries:
        output_path = output_dir / f"{query['query_id']}.json"
        if output_path.exists():
            continue
        question = semantic_question(query["text"])
        context = graph.query(question, param=QueryParam(mode="local", top_k=5, only_need_context=True))
        raw_ids = source_ids(context)
        if set(raw_ids) - visible:
            raise RuntimeError("TG-RAG recovered a source outside the frozen snapshot")
        evidence_ids = raw_ids[:5]
        (output_dir / f"{query['query_id']}.txt").write_text(str(context), encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {
                    "method": "TG-RAG pinned local retrieval with domain, CPU, and source-recovery compatibility adapters",
                    "official_commit": OFFICIAL_COMMIT,
                    "query_id": query["query_id"],
                    "snapshot_key": snapshot_key,
                    "semantic_question": question,
                    "evidence_ids": evidence_ids,
                    "raw_unique_source_count": len(raw_ids),
                    "candidate_count": len(visible),
                    "gold_read": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"TG-RAG {query['query_id']}: {len(evidence_ids)} source(s)", flush=True)
    cache_path = graph_dir / "kv_store_llm_response_cache.json"
    cache_entries = len(read(cache_path)) if cache_path.exists() else None
    outputs = sorted(output_dir.glob("*.json"))
    completion = {
        "snapshot_key": snapshot_key,
        "documents": len(corpus_paths),
        "queries": len(outputs),
        "source_counts": {path.stem: len(read(path)["evidence_ids"]) for path in outputs},
        "llm_cache_entries_after_build_and_queries": cache_entries,
        "exact_token_usage_available": False,
        "official_commit": OFFICIAL_COMMIT,
        "gold_read": False,
        "authoring_read": False,
        "input_hashes": {
            str(path.relative_to(ROOT)): sha(path)
            for path in [Path(__file__).resolve(), INPUT / "manifest.json", INPUT / "snapshot_mapping.json", INPUT / "queries.jsonl", FREEZE, PLAN, SUPPLEMENT, SOURCE_SUPPLEMENT, TEXT_PLAN, ADAPTER, SOURCE_ADAPTER]
        },
        "query_output_hashes": {path.name: sha(path) for path in outputs},
    }
    seed_provenance = snapshot_run / "seed_provenance.json"
    if seed_provenance.exists():
        completion["seed_provenance_hash"] = sha(seed_provenance)
    completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": snapshot_key, "documents": len(corpus_paths), "queries": len(outputs), "source_counts": completion["source_counts"]}, ensure_ascii=False))


def finalize():
    mapping = read(INPUT / "snapshot_mapping.json")
    completions = []
    for snapshot_key in mapping:
        path = RUN / "snapshots" / snapshot_key / "completion.json"
        if not path.exists():
            raise RuntimeError(f"missing snapshot completion: {snapshot_key}")
        completions.append(read(path))
    result = {
        "snapshots": len(completions),
        "queries": sum(row["queries"] for row in completions),
        "documents_across_snapshots": sum(row["documents"] for row in completions),
        "official_commit": OFFICIAL_COMMIT,
        "gold_read": False,
        "exact_token_usage_available": False,
        "snapshot_completion_hashes": {
            row["snapshot_key"]: sha(RUN / "snapshots" / row["snapshot_key"] / "completion.json") for row in completions
        },
    }
    if result["queries"] != 16:
        raise RuntimeError(f"incomplete TG-RAG query count: {result['queries']}")
    (RUN / "completion.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        finalize()
    elif args.snapshot:
        run_snapshot(args.snapshot)
    else:
        raise SystemExit("provide --snapshot or --finalize")


if __name__ == "__main__":
    main()
