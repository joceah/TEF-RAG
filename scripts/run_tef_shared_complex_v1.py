"""Gold-free TEF and shared-baseline rankings on the frozen v8 set."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.temporal_retrieval_eval_v1_lib import Encoder
from tef_rag_v4 import NeutralScopeEvidenceFlowRetrieverV4
import numpy as np


DATA = ROOT / "data/generated/tef_complex_dev_candidate_v8"
FREEZE = ROOT / "experiments/analyses/tef_complex_dev_candidate_v8/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_TA_TG复杂链开发对比_v1_预登记.md"
RELATION_RUN = ROOT / "experiments/runs/tef_relation_projection_complex_v2"
RUN = ROOT / "experiments/runs/tef_shared_complex_v1"


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(text):
    result = []
    for part in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower()):
        if "\u4e00" <= part[0] <= "\u9fff":
            result.extend(part)
            result.extend(part[index : index + 2] for index in range(len(part) - 1))
        else:
            result.append(part)
    return result


def question_core(text):
    return text.split("；", 1)[-1]


def visible(record, query):
    return (
        record["asset_id"] == query["asset_id"]
        and record["event_time"] <= query["query_time"]
        and record["available_at"] <= query["query_time"]
    )


def hybrid_scores(docs, pool, query_text, doc_vectors, query_vector):
    counts = [Counter(tokens(doc["text"])) for doc in docs]
    lengths = np.asarray([sum(count.values()) for count in counts], dtype=np.float64)
    mean = max(float(lengths[pool].mean()), 1.0)
    norm = 1.5 * (0.25 + 0.75 * lengths / mean)
    bm25 = np.zeros(len(docs), dtype=np.float64)
    for term in tokens(query_text):
        tf = np.asarray([count[term] for count in counts], dtype=np.float64)
        df = int(np.count_nonzero(tf[pool]))
        if df:
            bm25 += math.log(1 + (len(pool) - df + 0.5) / (df + 0.5)) * tf * 2.5 / (tf + norm)
    dense = doc_vectors @ query_vector
    score = np.zeros(len(docs), dtype=np.float64)
    for values in (bm25, dense):
        ranked = sorted(pool, key=lambda index: (-float(values[index]), docs[index]["id"]))
        for rank, index in enumerate(ranked):
            score[index] += 1 / (61 + rank)
    return score


def main():
    if not FREEZE.exists() or not (RELATION_RUN / "preparation_complete.json").exists():
        raise RuntimeError("frozen data and completed public relation projection required")
    if RUN.exists():
        raise RuntimeError("refusing to overwrite TEF/shared ranking run")
    docs = lines(DATA / "evidence.jsonl")
    queries = lines(DATA / "queries.jsonl")
    assets = read(DATA / "assets.json")
    relations = []
    relation_paths = sorted((RELATION_RUN / "public_relations").glob("*.json"))
    for path in relation_paths:
        relations.extend(read(path)["relations"])
    encoder = Encoder()
    doc_vectors = encoder.encode([doc["text"] for doc in docs])
    query_vectors = encoder.encode([question_core(query["text"]) for query in queries])
    retriever = NeutralScopeEvidenceFlowRetrieverV4(docs, assets, relations, top_k=5)
    RUN.mkdir(parents=True)
    np.save(RUN / "embeddings.npy", np.vstack([doc_vectors, query_vectors]))
    output_dir = RUN / "queries"
    output_dir.mkdir()
    candidate_counts = []
    for query_index, query in enumerate(queries):
        pool = [index for index, doc in enumerate(docs) if visible(doc, query)]
        candidate_counts.append(len(pool))
        if len(pool) not in {8, 12}:
            raise RuntimeError(f"unexpected candidate count for {query['query_id']}: {len(pool)}")
        scores = hybrid_scores(docs, pool, question_core(query["text"]), doc_vectors, query_vectors[query_index])
        relevance = {doc["id"]: float(scores[index]) for index, doc in enumerate(docs)}
        hybrid = [docs[index]["id"] for index in sorted(pool, key=lambda index: (-float(scores[index]), docs[index]["id"]))[:5]]
        latest = [
            docs[index]["id"]
            for index in sorted(pool, key=lambda index: (docs[index]["event_time"], docs[index]["id"]), reverse=True)[:5]
        ]
        tef = retriever.retrieve(query, relevance)
        if set(tef["evidence_ids"]) - {docs[index]["id"] for index in pool}:
            raise RuntimeError("TEF returned outside the shared candidate pool")
        (output_dir / f"{query['query_id']}.json").write_text(
            json.dumps(
                {
                    "query_id": query["query_id"],
                    "candidate_count": len(pool),
                    "methods": {
                        "scoped_hybrid": {"evidence_ids": hybrid},
                        "scoped_latest": {"evidence_ids": latest},
                        "tef_v4": tef,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    inputs = [
        Path(__file__).resolve(),
        ROOT / "tef_rag_v4/retriever.py",
        ROOT / "tef_rag_v3/retriever.py",
        DATA / "manifest.json",
        DATA / "evidence.jsonl",
        DATA / "queries.jsonl",
        DATA / "assets.json",
        FREEZE,
        PLAN,
        RELATION_RUN / "preparation_complete.json",
        *relation_paths,
    ]
    completion = {
        "queries": len(queries),
        "methods": ["scoped_hybrid", "scoped_latest", "tef_v4"],
        "top_k": 5,
        "candidate_counts": sorted(set(candidate_counts)),
        "relations": len(relations),
        "gold_read": False,
        "authoring_read": False,
        "input_hashes": {str(path.relative_to(ROOT)): sha(path) for path in inputs},
        "embedding_sha256": sha(RUN / "embeddings.npy"),
    }
    (RUN / "retrieval_complete.json").write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(queries), "relations": len(relations), "candidate_counts": sorted(set(candidate_counts))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
