"""Gold-free TEF-v5 and shared baseline rankings on the frozen holdout."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from baseline_adapters.query_text_v2 import semantic_question
from scripts.run_tef_shared_complex_v1 import hybrid_scores, visible
from scripts.temporal_retrieval_eval_v1_lib import Encoder
from tef_rag_v5 import QueryConditionedSetEvidenceRetrieverV5
import numpy as np


DATA = ROOT / "data/generated/tef_v5_holdout_v3"
FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_RAG_v5_holdout_v3_投影与排名预登记.md"
PROJECTION = ROOT / "experiments/runs/tef_v5_holdout_projections_v6"
RUN = ROOT / "experiments/runs/tef_v5_holdout_shared_v1"


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if not FREEZE.exists() or not (PROJECTION / "preparation_complete.json").exists():
        raise RuntimeError("frozen data and completed projections required")
    if RUN.exists():
        raise RuntimeError("refusing to overwrite shared ranking run")
    docs = lines(DATA / "evidence.jsonl")
    queries = lines(DATA / "queries.jsonl")
    assets = read(DATA / "assets.json")
    relations = []
    roles = {}
    graph_paths = sorted((PROJECTION / "public_graphs").glob("*.json"))
    profile_paths = sorted((PROJECTION / "query_profiles").glob("*.json"))
    profiles = {}
    for path in graph_paths:
        row = read(path)
        relations.extend(row["relations"])
        for role in row["roles"]:
            if role["id"] in roles:
                raise RuntimeError("duplicate role projection")
            roles[role["id"]] = {"role_scores": role["role_scores"]}
    for path in profile_paths:
        for row in read(path)["profiles"]:
            if row["query_id"] in profiles:
                raise RuntimeError("duplicate query profile")
            profiles[row["query_id"]] = {
                "selection_mode": row["selection_mode"],
                "role_demands": row["role_demands"],
                "relation_demands": row["relation_demands"],
            }
    if set(roles) != {doc["id"] for doc in docs} or set(profiles) != {query["query_id"] for query in queries}:
        raise RuntimeError("projection coverage mismatch")

    encoder = Encoder()
    doc_vectors = encoder.encode([doc["text"] for doc in docs])
    query_vectors = encoder.encode([semantic_question(query["text"]) for query in queries])
    retriever = QueryConditionedSetEvidenceRetrieverV5(
        docs,
        assets,
        relations,
        roles=roles,
        top_k=5,
        beam_width=64,
    )
    RUN.mkdir(parents=True)
    np.save(RUN / "embeddings.npy", np.vstack([doc_vectors, query_vectors]))
    output_dir = RUN / "queries"
    output_dir.mkdir()
    candidate_counts = []
    profile_modes = []
    for query_index, query in enumerate(queries):
        pool = [index for index, doc in enumerate(docs) if visible(doc, query)]
        candidate_counts.append(len(pool))
        if len(pool) not in {8, 12}:
            raise RuntimeError(f"unexpected candidate count for {query['query_id']}: {len(pool)}")
        scores = hybrid_scores(
            docs,
            pool,
            semantic_question(query["text"]),
            doc_vectors,
            query_vectors[query_index],
        )
        relevance = {doc["id"]: float(scores[index]) for index, doc in enumerate(docs)}
        hybrid = [
            docs[index]["id"]
            for index in sorted(pool, key=lambda index: (-float(scores[index]), docs[index]["id"]))[:5]
        ]
        latest = [
            docs[index]["id"]
            for index in sorted(pool, key=lambda index: (docs[index]["event_time"], docs[index]["id"]), reverse=True)[:5]
        ]
        profile = profiles[query["query_id"]]
        profile_modes.append(profile["selection_mode"])
        tef = retriever.retrieve(query, relevance, query_profile=profile)
        shared_ids = {docs[index]["id"] for index in pool}
        for method, ids in (("scoped_hybrid", hybrid), ("scoped_latest", latest), ("tef_v5", tef["evidence_ids"])):
            if len(ids) > 5 or len(ids) != len(set(ids)) or set(ids) - shared_ids:
                raise RuntimeError(f"invalid shared output: {query['query_id']}/{method}")
        (output_dir / f"{query['query_id']}.json").write_text(
            json.dumps(
                {
                    "query_id": query["query_id"],
                    "candidate_count": len(pool),
                    "candidate_ids": sorted(shared_ids),
                    "methods": {
                        "scoped_hybrid": {"evidence_ids": hybrid},
                        "scoped_latest": {"evidence_ids": latest},
                        "tef_v5": tef,
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
        ROOT / "tef_rag_v5/retriever.py",
        ROOT / "tef_rag_v5/DESIGN.md",
        ROOT / "baseline_adapters/query_text_v2.py",
        DATA / "manifest.json",
        DATA / "evidence.jsonl",
        DATA / "queries.jsonl",
        DATA / "assets.json",
        FREEZE,
        PLAN,
        PROJECTION / "preparation_complete.json",
        *graph_paths,
        *profile_paths,
    ]
    completion = {
        "status": "retrieval_complete_gold_free",
        "queries": len(queries),
        "methods": ["scoped_hybrid", "scoped_latest", "tef_v5"],
        "top_k": 5,
        "candidate_counts": sorted(set(candidate_counts)),
        "relations": len(relations),
        "query_profile_modes": {mode: profile_modes.count(mode) for mode in sorted(set(profile_modes))},
        "gold_read": False,
        "authoring_read": False,
        "shared_candidate_ids_persisted": True,
        "input_hashes": {str(path.relative_to(ROOT)): sha(path) for path in inputs},
        "embedding_sha256": sha(RUN / "embeddings.npy"),
        "query_output_hashes": {path.name: sha(path) for path in sorted(output_dir.glob("*.json"))},
    }
    (RUN / "retrieval_complete.json").write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "queries": len(queries),
                "relations": len(relations),
                "candidate_counts": sorted(set(candidate_counts)),
                "query_profile_modes": completion["query_profile_modes"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
