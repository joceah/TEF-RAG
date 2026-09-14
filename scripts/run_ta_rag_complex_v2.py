"""TA-RAG downstream compatibility run for queries without event intervals."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_ta_rag_complex_v1 as base
from baseline_adapters.query_text_v2 import semantic_question


RUN = ROOT / "experiments/runs/ta_rag_complex_v2"
SUPPLEMENT = ROOT / "plans/复杂链知识截止文本规范化_v2_补充.md"
ADAPTER = ROOT / "baseline_adapters/query_text_v2.py"


class NoEventIntervalParser:
    """Select the official no-temporal-decomposition branch after snapshotting."""

    parsed = None

    def temporal_process_sentence(self, text, chance=20):
        self.parsed = {"rephrased_sentence": text, "temporal_decomposition": []}
        return self.parsed


def main():
    if not base.FREEZE.exists() or not (base.INPUT / "manifest.json").exists():
        raise RuntimeError("frozen data and prepared snapshots required")
    if RUN.exists():
        raise RuntimeError("refusing to overwrite completed TA-RAG compatibility run")
    RUN.mkdir(parents=True)
    output_dir = RUN / "queries"
    output_dir.mkdir()
    queries = base.lines(base.INPUT / "queries.jsonl")
    by_snapshot = {}
    for query in queries:
        by_snapshot.setdefault(query["snapshot_key"], []).append(query)
    for snapshot_key, snapshot_queries in sorted(by_snapshot.items()):
        corpus_path = base.INPUT / "snapshots" / snapshot_key / "ta_corpus.json"
        rows = base.read(corpus_path)
        index = base.ta_build.create_faiss_flat_index(384, base.faiss.METRIC_INNER_PRODUCT)
        index, metadata, interval_index = base.ta_build.load_embed_and_build_indices_for_tarag(rows, index)
        for query in snapshot_queries:
            question = semantic_question(query["text"])
            parser = NoEventIntervalParser()
            base.ta_query.LLM_CLIENT_A = parser
            ranked, total, semantic, temporal, embedding = base.ta_query.ta_rag_retrieval(
                question, index, metadata, interval_index, top_k=5
            )
            result = {
                "method": "TA-RAG pinned downstream no-event-interval compatibility run",
                "official_commit": base.OFFICIAL_COMMIT,
                "query_id": query["query_id"],
                "snapshot_key": snapshot_key,
                "semantic_question": question,
                "temporal_parse": parser.parsed,
                "evidence_ids": [item["corpus_uid"] for item in ranked],
                "candidate_count": len(rows),
                "gold_read": False,
                "llm_requests": [],
                "timing_seconds": {
                    "total": total,
                    "semantic": semantic,
                    "temporal_parser": temporal,
                    "embedding": embedding,
                },
            }
            (output_dir / f"{query['query_id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"TA-RAG compat {query['query_id']}: {len(result['evidence_ids'])} records", flush=True)
    inputs = [
        Path(__file__).resolve(),
        ROOT / "scripts/run_ta_rag_complex_v1.py",
        ADAPTER,
        SUPPLEMENT,
        base.INPUT / "manifest.json",
        base.INPUT / "queries.jsonl",
        base.FREEZE,
        base.PLAN,
    ]
    outputs = sorted(output_dir.glob("*.json"))
    completion = {
        "queries": len(outputs),
        "snapshots": len(by_snapshot),
        "top_k": 5,
        "official_commit": base.OFFICIAL_COMMIT,
        "gold_read": False,
        "authoring_read": False,
        "usage": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "temporal_parser_status": "deterministic empty decomposition after official parser v1 failed; not an official-LLM-parser result",
        "compatibility": {
            "retrieval_branch": "official no-temporal-decomposition full semantic search",
            "embedding": "shared local multilingual MiniLM 384d",
            "interval_index": "linear NCLS API-compatible overlap implementation",
            "vector_index": "exact NumPy inner-product flat index",
        },
        "input_hashes": {str(path.relative_to(ROOT)): base.sha(path) for path in inputs},
        "query_output_hashes": {path.name: base.sha(path) for path in outputs},
    }
    (RUN / "completion.json").write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(outputs), "llm_requests": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
