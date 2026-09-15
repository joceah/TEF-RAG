"""Validate committed TEF-RAG v6 semantic benchmark public artifacts.

Reads logical JSONL directly if materialized; otherwise reads committed .xz transport blobs.
Optional --sealed validates the private evaluator artifact by hash/count only plus structural references.
"""
from __future__ import annotations
import argparse, hashlib, json, lzma
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_BASE=ROOT/"data/generated/tef_v6_temporal_hard_benchmark_v1"

def dt(x): return datetime.fromisoformat(x)
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def rows_bytes(b): return [json.loads(x) for x in b.decode("utf-8").splitlines() if x.strip()]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--base", default=str(DEFAULT_BASE))
    ap.add_argument("--sealed", default=None)
    a=ap.parse_args()
    b=Path(a.base); errors=[]; req=lambda ok,msg: errors.append(msg) if not ok else None
    man=json.loads((b/"manifest.json").read_text(encoding="utf-8"))
    tm=json.loads((b/"transport_manifest.json").read_text(encoding="utf-8"))
    cache={}
    def logical_bytes(rel):
        p=b/rel
        if p.exists(): data=p.read_bytes()
        else:
            meta=tm[rel]
            chunks=[]
            import base64
            for part in meta["parts"]:
                cp=b/"compressed"/Path(part["repo_path"]).name
                raw=base64.b64decode(cp.read_text(encoding="ascii"))
                req(sha_bytes(raw)==part["sha256"],f"part hash mismatch: {cp.name}")
                chunks.append(raw)
            comp=b"".join(chunks)
            req(sha_bytes(comp)==meta["compressed_sha256"],f"compressed hash mismatch: {rel}")
            data=lzma.decompress(comp)
        req(sha_bytes(data)==man["public_artifact_hashes"][rel],f"hash mismatch: {rel}")
        return data
    def rows(rel):
        if rel not in cache: cache[rel]=rows_bytes(logical_bytes(rel))
        return cache[rel]

    ch=rows("public/chains_development.jsonl")+rows("public/chains_validation.jsonl")+rows("public/chains_test.jsonl")
    qs=rows("public/queries_development.jsonl")+rows("public/queries_validation.jsonl")+rows("public/queries_test.jsonl")
    ev=rows("public/evidence.jsonl")
    gd=rows("public/gold_development.jsonl")+rows("public/gold_validation.jsonl")
    req(len(ch)==400,"expected 400 chains")
    req(len(qs)==2400,"expected 2400 queries")
    req(len({c["asset_id"] for c in ch})==100,"expected 100 assets")
    req(not (b/"public/gold_test.jsonl").exists(),"test gold must not be public")
    testq=[q for q in qs if q["split"]=="test"]
    req(all("difficulty_labels" not in q and "primary_difficulty" not in q for q in testq),"test labels leaked in queries")
    testc=[c for c in ch if c["split"]=="test"]
    req(all("difficulty_labels" not in c and "primary_difficulty" not in c for c in testc),"test labels leaked in chain metadata")
    intents=Counter(q["intent_id"] for q in qs)
    req(set(intents.values())=={2},"each intent must have exactly two phrasings")
    ci=defaultdict(set)
    for q in qs: ci[q["chain_id"]].add(q["intent_id"])
    req(all(len(v)==3 for v in ci.values()),"each chain must have 3 primary intents")
    evm={x["evidence_id"]:x for x in ev}; qm={q["query_id"]:q for q in qs}
    allowed={"supports","updates","supersession","contrasts","prerequisite","verifies","governs","qualifies","resolves","preserves_uncertainty"}
    for g in gd:
        q=qm[g["query_id"]]
        groups={x["group_id"]:set(x["acceptable_evidence_ids"]) for x in g["required_groups"]}
        req(len(groups)<=5,f"{g['query_id']}: >5 required groups")
        for ids in groups.values():
            for eid in ids:
                req(eid in evm,f"{g['query_id']}: missing evidence {eid}")
                if eid in evm:
                    x=evm[eid]
                    req(x["chain_id"]==g["chain_id"],f"{g['query_id']}: cross-chain gold")
                    req(dt(x["event_time"])<=dt(q["query_time"]) and dt(x["available_at"])<=dt(q["query_time"]),f"{g['query_id']}: invisible gold")
        for ed in g["required_flow_edges"]:
            req(ed["relation_type"] in allowed,f"{g['query_id']}: invalid relation")
            req(ed["from_group"] in groups and ed["to_group"] in groups,f"{g['query_id']}: invalid group edge")
            for p in ed["allowed_endpoint_pairs"]:
                req(p[0] in groups[ed["from_group"]] and p[1] in groups[ed["to_group"]],f"{g['query_id']}: endpoint/group mismatch")
    for x in ev:
        if x["event_type"]=="procedure_applicability":
            for f in ("procedure_version","valid_from","valid_to","supersedes","withdrawn_at","model_scope"):
                req(f in x,f"{x['evidence_id']}: procedure field {f} missing")
            req(x.get("asset_model") in x.get("model_scope",[]),f"{x['evidence_id']}: model scope mismatch")

    # Small plain metadata hashes
    for rel,h in man["public_artifact_hashes"].items():
        if rel in tm: continue
        p=b/rel
        req(p.exists(),f"missing public metadata: {rel}")
        if p.exists(): req(sha_bytes(p.read_bytes())==h,f"hash mismatch: {rel}")

    if a.sealed:
        sp=Path(a.sealed); req(sp.exists(),"sealed artifact missing")
        if sp.exists():
            req(sha_bytes(sp.read_bytes())==man["sealed_test"]["sha256"],"sealed SHA mismatch")
            sr=rows_bytes(sp.read_bytes())
            req(len(sr)==man["sealed_test"]["record_count"],"sealed record count mismatch")
            req(all(r["query"]["split"]=="test" for r in sr),"sealed artifact contains non-test rows")
    if errors:
        raise SystemExit("semantic benchmark validation failed:\n- "+"\n- ".join(errors))
    print(f"semantic benchmark validation passed: chains={len(ch)} queries={len(qs)} evidence={len(ev)} public_gold={len(gd)}")
if __name__=="__main__": main()
