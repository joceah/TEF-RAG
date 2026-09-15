"""Deterministic structural validation for the 16-chain semantic authoring pilot."""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/generated/tef_v6_authoring_pilot_v1"
DIFFICULTIES = {"MULTI_EPISODE_DISAMBIGUATION","CUTOFF_SENSITIVE","LATE_ARRIVING_EVIDENCE","SUPERSEDED_DIAGNOSIS","PROCEDURE_VERSIONING","CROSS_SOURCE_REQUIRED","SIMILAR_SYMPTOM_DIFFERENT_CAUSE","PERSISTENT_UNCERTAINTY"}

def rows(path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
def dt(x): return datetime.fromisoformat(x)

def main():
    chains=rows(BASE/"chains/pilot_chains.jsonl"); ev=rows(BASE/"evidence/pilot_evidence.jsonl"); qs=rows(BASE/"queries/pilot_queries.jsonl"); gold=rows(BASE/"gold/pilot_gold.jsonl")
    errors=[]; require=lambda ok,msg: errors.append(msg) if not ok else None
    require(len(chains)==16,"expected 16 chains")
    counts=Counter(c["difficulty_labels"][0] for c in chains); require(set(counts)==DIFFICULTIES and all(v==2 for v in counts.values()),"each difficulty must occur twice")
    evmap={e["evidence_id"]:e for e in ev}; qmap={q["query_id"]:q for q in qs}
    for c in chains:
        ce=[e for e in ev if e["chain_id"]==c["chain_id"]]; cq=[q for q in qs if q["chain_id"]==c["chain_id"]]
        require(8<=len(ce)<=14,f"{c['chain_id']}: evidence count")
        require(2<=len(cq)<=4,f"{c['chain_id']}: intent count")
        require(all(d not in q["query_text"] for q in cq for d in DIFFICULTIES),f"{c['chain_id']}: difficulty leak")
        require(all(len(e["text"])>=8 and "episode " not in e["text"].lower() and "阶段 " not in e["text"] for e in ce),f"{c['chain_id']}: mechanical evidence")
        d=c["difficulty_labels"][0]
        if d=="LATE_ARRIVING_EVIDENCE": require(any(dt(e["event_time"])<dt(e["available_at"]) for e in ce),f"{c['chain_id']}: no late arrival")
        if d=="SUPERSEDED_DIAGNOSIS": require(any(e["event_type"]=="diagnosis" for e in ce) and any(e["event_type"]=="correction" for e in ce),f"{c['chain_id']}: no supersession")
        if d=="PROCEDURE_VERSIONING": require(all(any(f"V{i}" in e["text"] for e in ce) for i in (1,2,3)),f"{c['chain_id']}: missing versions")
        if d=="MULTI_EPISODE_DISAMBIGUATION": require(len({e["episode_id"] for e in ce})>=2,f"{c['chain_id']}: no distinct episodes")
        if d=="CROSS_SOURCE_REQUIRED": require(len({e["source_type"] for e in ce})>=3,f"{c['chain_id']}: not cross-source")
        if d=="CUTOFF_SENSITIVE": require(len(cq)==2 and cq[0]["query_text"]==cq[1]["query_text"] and cq[0]["query_time"]!=cq[1]["query_time"],f"{c['chain_id']}: cutoff pair invalid")
    for g in gold:
        q=qmap.get(g["query_id"]); require(q is not None,f"missing query {g['query_id']}")
        gids={x["group_id"] for x in g["required_groups"]}
        used=set()
        for group in g["required_groups"]:
            require(group["acceptable_evidence_ids"],f"{g['query_id']}: empty group")
            for eid in group["acceptable_evidence_ids"]: require(eid in evmap,f"{g['query_id']}: invalid evidence {eid}"); used.add(eid)
        for edge in g["required_flow_edges"]:
            require(edge["from_group"] in gids and edge["to_group"] in gids,f"{g['query_id']}: invalid group edge")
            require(bool(edge["allowed_endpoint_pairs"]),f"{g['query_id']}: empty endpoint pairs")
            for a,b in edge["allowed_endpoint_pairs"]: require(a in evmap and b in evmap,f"{g['query_id']}: invalid pair")
        for eid in used:
            require(dt(evmap[eid]["event_time"])<=dt(q["query_time"]) and dt(evmap[eid]["available_at"])<=dt(q["query_time"]),f"{g['query_id']}: gold evidence not visible {eid}")
        if g["persistent_uncertainty"]: require(any(evmap[e]["event_type"]=="uncertainty" for e in used),f"{g['query_id']}: uncertainty missing")
    require(sum(c["flowcomplete_ambiguous_possible"] for c in chains)>=6,"fewer than 6 FlowComplete-ambiguous chains")
    if errors: raise SystemExit("pilot validation failed:\n- "+"\n- ".join(errors))
    print(f"pilot validation passed: chains={len(chains)} evidence={len(ev)} queries={len(qs)} ambiguous={sum(c['flowcomplete_ambiguous_possible'] for c in chains)}")
if __name__=="__main__": main()
