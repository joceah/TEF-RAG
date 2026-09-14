"""Prepare gold-free, visibility-safe native inputs for TA-RAG and TG-RAG."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path


def _lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def _visible(record, cutoff):
    limit = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    occurred = datetime.fromisoformat(record["event_time"].replace("Z", "+00:00"))
    available = datetime.fromisoformat(record["available_at"].replace("Z", "+00:00"))
    return occurred <= limit and available <= limit


def _plus_second(iso_time):
    parsed = datetime.fromisoformat(iso_time.replace("Z", "+00:00")) + timedelta(seconds=1)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _snapshot_key(asset_id, cutoff):
    digest = hashlib.sha256((asset_id + "\0" + cutoff).encode()).hexdigest()[:12]
    return _safe_name(asset_id) + "__" + digest


def prepare_snapshots(evidence_path, queries_path, output_dir):
    """Write per-asset, per-cutoff inputs without reading an evaluation file."""
    evidence_path = Path(evidence_path)
    queries_path = Path(queries_path)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise RuntimeError(f"Refusing to overwrite existing adapter output: {output_dir}")

    records = _lines(evidence_path)
    queries = _lines(queries_path)
    snapshots = {}
    query_rows = []
    for query in queries:
        key = _snapshot_key(query["asset_id"], query["query_time"])
        snapshots.setdefault(key, (query["asset_id"], query["query_time"]))
        query_rows.append({**query, "snapshot_key": key})

    mapping = {}
    for key, (asset_id, cutoff) in snapshots.items():
        visible = [record for record in records if record["asset_id"] == asset_id and _visible(record, cutoff)]
        root = output_dir / "snapshots" / key
        ta_rows = []
        for record in visible:
            ta_rows.append(
                {
                    "corpus_uid": record["id"],
                    "chunk_number": 0,
                    "chunk_text": record["text"],
                    "chunk_time_info": [
                        {
                            "event_time_interval": {
                                "begin": record["event_time"],
                                "end": _plus_second(record["event_time"]),
                            }
                        }
                    ],
                    "new_background": {
                        "begin": record["event_time"],
                        "end": _plus_second(record["event_time"]),
                        "estimate_doc_create_date": record["event_time"],
                    },
                }
            )
            tg_path = root / "tg_corpus" / (_safe_name(record["id"]) + ".txt")
            tg_path.parent.mkdir(parents=True, exist_ok=True)
            tg_path.write_text(
                "\n".join(
                    [
                        f"record_id: {record['id']}",
                        f"asset_id: {record['asset_id']}",
                        f"event_time: {record['event_time']}",
                        f"available_at: {record['available_at']}",
                        "content: " + record["text"],
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        _write_json(root / "ta_corpus.json", ta_rows)
        mapping[key] = {
            "asset_id": asset_id,
            "query_time": cutoff,
            "visible_record_ids": [record["id"] for record in visible],
        }

    _write_jsonl(output_dir / "queries.jsonl", query_rows)
    _write_json(output_dir / "snapshot_mapping.json", mapping)
    _write_json(
        output_dir / "manifest.json",
        {
            "adapter": "ta_tg_input_v1",
            "gold_read": False,
            "snapshot_count": len(mapping),
            "query_count": len(queries),
            "source_files": [str(evidence_path), str(queries_path)],
        },
    )
    return mapping
