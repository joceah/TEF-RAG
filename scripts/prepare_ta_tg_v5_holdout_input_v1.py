"""Prepare identical frozen visibility snapshots for TA-RAG and TG-RAG."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/tef_v5_holdout_v3"
FREEZE = ROOT / "experiments/analyses/tef_v5_holdout_v3/freeze_manifest.json"
PLAN = ROOT / "plans/TEF_RAG_v5_holdout_v3_投影与排名预登记.md"
RUN = ROOT / "experiments/runs/ta_tg_input_v5_holdout_v1"


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main():
    if not FREEZE.exists():
        raise RuntimeError("frozen holdout required")
    if RUN.exists():
        raise RuntimeError("refusing to overwrite prepared input")
    docs = lines(DATA / "evidence.jsonl")
    queries = lines(DATA / "queries.jsonl")
    snapshots = {}
    prepared_queries = []
    for query in queries:
        token = hashlib.sha256(f"{query['asset_id']}|{query['query_time']}".encode("utf-8")).hexdigest()[:12]
        key = f"{query['asset_id']}__{token}"
        visible = [
            doc
            for doc in docs
            if doc["asset_id"] == query["asset_id"]
            and doc["event_time"] <= query["query_time"]
            and doc["available_at"] <= query["query_time"]
        ]
        if len(visible) not in {8, 12}:
            raise RuntimeError(f"unexpected candidate count: {query['query_id']}")
        ids = sorted(doc["id"] for doc in visible)
        if key in snapshots and snapshots[key]["visible_record_ids"] != ids:
            raise RuntimeError("snapshot hash collision")
        snapshots[key] = {
            "asset_id": query["asset_id"],
            "query_time": query["query_time"],
            "visible_record_ids": ids,
            "candidate_count": len(ids),
        }
        prepared_queries.append({**query, "snapshot_key": key})

    for key, snapshot in snapshots.items():
        visible = [doc for doc in docs if doc["id"] in set(snapshot["visible_record_ids"])]
        ta_rows = []
        tg_dir = RUN / "snapshots" / key / "tg_corpus"
        tg_dir.mkdir(parents=True, exist_ok=True)
        for doc in visible:
            begin = datetime.fromisoformat(doc["event_time"].replace("Z", "+00:00"))
            end = (begin + timedelta(seconds=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
            ta_rows.append(
                {
                    "corpus_uid": doc["id"],
                    "chunk_number": 0,
                    "chunk_text": doc["text"],
                    "chunk_time_info": [{"event_time_interval": {"begin": doc["event_time"], "end": end}}],
                    "new_background": {
                        "begin": doc["event_time"],
                        "end": end,
                        "estimate_doc_create_date": doc["event_time"],
                    },
                }
            )
            (tg_dir / f"{doc['id']}.txt").write_text(
                "\n".join(
                    [
                        f"record_id: {doc['id']}",
                        f"asset_id: {doc['asset_id']}",
                        f"event_time: {doc['event_time']}",
                        f"available_at: {doc['available_at']}",
                        f"content: {doc['text']}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        write_json(RUN / "snapshots" / key / "ta_corpus.json", ta_rows)

    write_json(RUN / "snapshot_mapping.json", snapshots)
    write_jsonl(RUN / "queries.jsonl", prepared_queries)
    output_files = sorted(path for path in RUN.rglob("*") if path.is_file())
    manifest = {
        "adapter": "ta_tg_input_v5_holdout_v1",
        "gold_read": False,
        "authoring_read": False,
        "snapshot_count": len(snapshots),
        "query_count": len(prepared_queries),
        "candidate_counts": sorted({row["candidate_count"] for row in snapshots.values()}),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha(path)
            for path in [Path(__file__).resolve(), DATA / "evidence.jsonl", DATA / "queries.jsonl", FREEZE, PLAN]
        },
        "output_hashes": {str(path.relative_to(RUN)): sha(path) for path in output_files},
    }
    write_json(RUN / "manifest.json", manifest)
    print(json.dumps({"snapshots": len(snapshots), "queries": len(prepared_queries), "candidate_counts": manifest["candidate_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
