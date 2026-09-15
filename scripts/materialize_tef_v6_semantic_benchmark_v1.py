"""Materialize fixed public TEF-RAG v6 semantic benchmark files from committed base64+xz transport parts.

This script does NOT contain or reconstruct sealed test gold.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, lzma
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_BASE=ROOT/"data/generated/tef_v6_temporal_hard_benchmark_v1"
def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--base",default=str(DEFAULT_BASE)); a=ap.parse_args()
    b=Path(a.base); tm=json.loads((b/"transport_manifest.json").read_text(encoding="utf-8"))
    for logical,meta in tm.items():
        chunks=[]
        for part in meta["parts"]:
            p=ROOT/part["repo_path"]
            if not p.exists(): p=b/"compressed"/Path(part["repo_path"]).name
            raw=base64.b64decode(p.read_text(encoding="ascii"))
            if sha(raw)!=part["sha256"]: raise SystemExit(f"part hash mismatch: {p}")
            chunks.append(raw)
        comp=b"".join(chunks)
        if sha(comp)!=meta["compressed_sha256"]: raise SystemExit(f"compressed hash mismatch: {logical}")
        data=lzma.decompress(comp)
        if sha(data)!=meta["uncompressed_sha256"]: raise SystemExit(f"uncompressed hash mismatch: {logical}")
        out=b/logical; out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(data)
        print(f"materialized {logical}")
if __name__=="__main__": main()
