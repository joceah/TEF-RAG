import inspect, subprocess, sys
from pathlib import Path
from tef_rag_v6.set_scorer import LinearSetScorer, candidate_bank, set_features

def test_candidate_bank_full_deterministic_unique_and_contains_greedy():
    ids=[f"E{i:02d}" for i in range(20)]; scores={x:{"total":20-i} for i,x in enumerate(ids)}
    greedy=ids[:4]+[ids[18]]
    first=candidate_bank(ids,scores,greedy,ids[1:6])
    assert first==candidate_bank(ids,scores,greedy,ids[1:6])
    assert len(first)==len(set(first)) and all(len(x)==5 for x in first)
    assert tuple(sorted(greedy)) in first and any(ids[18] in x for x in first)
    assert len(first)<=3003+125+2

def test_top_m_exhaustive_count_without_extra_sets():
    ids=[f"E{i}" for i in range(15)]; scores={x:{"total":1} for x in ids}
    assert len(candidate_bank(ids,scores,ids[:5],ids[:5]))==3003

def test_feature_ablation_and_forbidden_fields():
    ids=tuple("ABCDE"); docs={x:{"event_type":"verification" if x=="E" else "diagnosis",
        "source_type":"log","event_time":f"2025-01-0{i+1}T00:00:00Z",
        "available_at":f"2025-01-0{i+1}T01:00:00Z","text":f"pump {x}","chain_id":"hidden"}
        for i,x in enumerate(ids)}
    scores={x:{"total":.5,"relevance":.4,"recency":.3,"role_compatibility":.2} for x in ids}
    edges=[{"source_id":"A","target_id":"E","relation_type":"verifies","confidence":.9}]
    hand={"node_sum":2.5,"edge_sum":.9,"role_coverage":1,"connectivity":.4,
          "uncertainty_consistency":1,"redundancy_penalty":0,"disconnected_penalty":3}
    common=dict(query={"query_text":"pump"},ids=ids,by_id=docs,node_scores=scores,edges=edges,
                role_demands={"verification"},set_score=hand)
    ag=set_features(**common,type_aware=False); aw=set_features(**common,type_aware=True)
    assert not any(k.startswith("relation=") for k in ag)
    assert aw["relation=verifies:count"]==1
    assert not any("chain_id" in k or "query_id" in k or "gold" in k for k in aw)
    assert aw==set_features(**common,type_aware=True)
    assert aw["longest_directed_path"]==2

def test_scorer_deterministic_and_gold_free():
    model=LinearSetScorer(["x"],[1],0,{})
    assert model.score({"x":2})==model.score({"x":2})
    assert "gold" not in inspect.signature(model.score).parameters

def test_http_is_fail_closed():
    from scripts.run_tef_rag_v6_stage3b import forbidden_http
    try:
        forbidden_http({}, 1)
    except RuntimeError as exc:
        assert "HTTP is forbidden" in str(exc)
    else:
        raise AssertionError("Stage3B must never allow HTTP")

def test_runner_has_no_test_split():
    root=Path(__file__).resolve().parents[1]
    p=subprocess.run([sys.executable,str(root/"scripts/run_tef_rag_v6_stage3b.py"),"--split","test"],
                     cwd=root,capture_output=True,text=True)
    assert p.returncode!=0 and "invalid choice" in p.stderr
