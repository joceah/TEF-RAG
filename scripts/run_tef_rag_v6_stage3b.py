"""Train/evaluate cache-only relation-aware Stage 3B full-set scorers."""
from __future__ import annotations
import argparse, hashlib, json, platform, statistics, sys, time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import numpy as np, sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from scripts.run_tef_rag_v6_stage1 import load_inputs, write_json
from scripts.run_tef_rag_v6_stage2a import build_runtime
from scripts.run_tef_rag_v6_stage3a import group_split, digest
from tef_rag_v6.evaluation import average, evaluate_prediction, flow_complete
from tef_rag_v6.llm_relation import QueryConditionedRelationScorer
from tef_rag_v6.pair_proposal import LinearPairProposer
from tef_rag_v6.set_scorer import BANK_VERSION, LinearSetScorer, candidate_bank, set_features

DEFAULT_CONFIG=ROOT/"configs/tef_rag_v6_stage3b_set_scorer.json"
TAXONOMY=(ROOT/"configs/tef_rag_v6_relation_taxonomy.json")

def forbidden_http(*args,**kwargs): raise RuntimeError("Stage3B cache miss: HTTP is forbidden")

def runtime(raw):
    stage3a=json.loads((ROOT/raw["stage3a_config"]).read_text(encoding="utf-8"))
    b1=json.loads((ROOT/stage3a["stage2b1_config"]).read_text(encoding="utf-8"))
    _,base,_,client,retriever=build_runtime(ROOT/b1["stage2a_config"])
    freeze=json.loads((ROOT/stage3a["output_dir"]/"development_freeze.json").read_text(encoding="utf-8"))
    proposer=LinearPairProposer.load(ROOT/stage3a["artifact_dir"]/"model.json")
    client.transport=forbidden_http
    retriever.config=replace(base,search_pool_k=b1["search_pool_k"],**b1["beam"])
    retriever.relation_scorer=QueryConditionedRelationScorer(client,retriever.config.relation_threshold,
                                                              proposer,freeze["pair_budget"])
    return stage3a,freeze,client,retriever

def context(query,retriever):
    prediction=retriever.retrieve(query,relation_mode="llm",search_mode="greedy",prefilter_mode="learned")
    diag=prediction["relation_diagnostics"]
    if diag["llm_called_pair_count"] or diag["request_count"] or diag["cache_hit_count"]!=diag["cache_lookup_count"]:
        raise RuntimeError("Stage3B requires 100% Stage3A cache hits")
    public=retriever._public_query(query)
    eligible=[x for x in retriever.candidate_retrieval(public)
              if retriever.temporal_eligibility(x["document"],public)[0]]
    scores=retriever._node_scores(public,eligible)
    pool=prediction["search_diagnostics"]["search_pool_ids"]
    demands=retriever._role_demands(public["query_text"])
    raw_ids,_=retriever._select_flow([{"document":retriever.by_id[x]} for x in pool],scores,
        prediction["relation_graph"],demands,use_relations=True,use_flow=True,search_mode="raw_beam")
    bank=candidate_bank(pool,scores,prediction["selected_evidence_ids"],raw_ids)
    return public,prediction,scores,demands,bank

def features_for(ids,public,prediction,scores,demands,retriever,type_aware):
    hand=retriever._set_score(ids,scores,prediction["relation_graph"],demands,use_relations=True)
    return set_features(public,ids,retriever.by_id,scores,prediction["relation_graph"],demands,hand,type_aware),hand

def collect_training(queries,gold_by_id,retriever,groups):
    agnostic_rows,aware_rows,labels,stats=[],[],[],Counter(); sizes=[]
    started=time.perf_counter()
    for index,q in enumerate(queries,1):
        if str(q["chain_id"]) not in groups: continue
        public,pred,scores,demands,bank=context(q,retriever); gold=gold_by_id[q["query_id"]]
        candidates=[]; positive=[]; negative=[]
        for ids in bank:
            feat,hand=features_for(ids,public,pred,scores,demands,retriever,True)
            item=(ids,feat,{k:v for k,v in feat.items() if not k.startswith("relation=")},hand["total"])
            (positive if flow_complete(list(ids),gold) else negative).append(item)
        positive=positive[:50]
        hard=sorted(negative,key=lambda x:(-x[3],x[0]))[:50]
        diverse=[x for i,x in enumerate(negative) if i % max(len(negative)//20,1)==0][:20]
        chosen=positive+list({x[0]:x for x in hard+diverse}.values())
        aware_rows.extend(x[1] for x in chosen); agnostic_rows.extend(x[2] for x in chosen)
        labels.extend([int(flow_complete(list(x[0]),gold)) for x in chosen])
        stats.update(queries=1,positive_sets=len(positive),negative_sets=len(chosen)-len(positive),
                     queries_with_positive=bool(positive),bank_oracle=bool(positive))
        sizes.append(len(bank))
        if index%80==0: print(f"training features: {index}/{len(queries)}",flush=True)
    stats["candidate_sets"]=sum(sizes); stats["runtime_seconds"]=time.perf_counter()-started
    return agnostic_rows,aware_rows,np.asarray(labels,dtype=np.int8),dict(stats),sizes

def fit(rows,labels,raw,metadata):
    started=time.perf_counter(); vectorizer=DictVectorizer(sparse=True,sort=True)
    matrix=vectorizer.fit_transform(rows)
    clf=LogisticRegression(random_state=raw["seed"],**raw["model_hyperparameters"]).fit(matrix,labels)
    return LinearSetScorer(vectorizer.feature_names_,clf.coef_[0].tolist(),float(clf.intercept_[0]),metadata),time.perf_counter()-started

def prediction_for(ids,base,retriever):
    selected=set(ids); edges=[e for e in base["relation_graph"] if e["source_id"] in selected and e["target_id"] in selected]
    return {"selected_evidence_ids":list(ids),"relations":edges,
            "uncertainty":retriever._uncertainty_state(list(ids),base["query_text"])}

def evaluate(queries,gold_by_id,retriever,agnostic,aware):
    metric_names=("stage3a_greedy","bank_handcrafted","learned_type_agnostic","learned_type_aware")
    metrics={x:[] for x in metric_names}; bank_sizes=[]; oracle=0; runtimes=Counter(); cache=Counter()
    for index,q in enumerate(queries,1):
        public,pred,scores,demands,bank=context(q,retriever); gold=gold_by_id[q["query_id"]]
        cache.update(lookups=pred["relation_diagnostics"]["cache_lookup_count"],hits=pred["relation_diagnostics"]["cache_hit_count"])
        bank_sizes.append(len(bank)); oracle+=any(flow_complete(list(ids),gold) for ids in bank)
        if not bank:
            base_ids=tuple(pred["selected_evidence_ids"])
            public_base={**pred,"query_text":public["query_text"]}
            row=evaluate_prediction(prediction_for(base_ids,public_base,retriever),gold,5)
            for name in metric_names: metrics[name].append(row)
            continue
        hand=[]; ag=[]; aw=[]; started=time.perf_counter()
        for ids in bank:
            fw,h=features_for(ids,public,pred,scores,demands,retriever,True)
            fa={k:v for k,v in fw.items() if not k.startswith("relation=")}
            hand.append((h["total"],ids)); ag.append((agnostic.score(fa),ids)); aw.append((aware.score(fw),ids))
        runtimes["seconds"]+=time.perf_counter()-started
        choices={"stage3a_greedy":tuple(pred["selected_evidence_ids"]),
                 "bank_handcrafted":sorted(hand,key=lambda x:(-x[0],x[1]))[0][1],
                 "learned_type_agnostic":sorted(ag,key=lambda x:(-x[0],x[1]))[0][1],
                 "learned_type_aware":sorted(aw,key=lambda x:(-x[0],x[1]))[0][1]}
        public_base={**pred,"query_text":public["query_text"]}
        for name,ids in choices.items(): metrics[name].append(evaluate_prediction(prediction_for(ids,public_base,retriever),gold,5))
        if index%20==0 or index==len(queries): print(f"evaluation: {index}/{len(queries)}",flush=True)
    return ({k:average(v) for k,v in metrics.items()},
            {"query_count":len(queries),"mean_sets_per_query":statistics.mean(bank_sizes),
             "median_sets_per_query":statistics.median(bank_sizes),"max_sets_per_query":max(bank_sizes),
             "flow_complete_oracle_count":oracle,"flow_complete_oracle":oracle/len(queries)},
            {"lookups":cache["lookups"],"hits":cache["hits"],"hit_rate":cache["hits"]/cache["lookups"],
             "new_http_requests":0},runtimes["seconds"]/len(queries))

def cost_sensitivity(queries,gold_by_id,retriever):
    modes={"rule_improved":("improved",None),"learned_top24":("learned",24),"frozen_top32":("learned",32)}
    output={}; original=retriever.relation_scorer.pair_budget
    for name,(mode,budget) in modes.items():
        if budget: retriever.relation_scorer.pair_budget=budget
        rows=[]; pairs=[]; hits=lookups=0
        for q in queries:
            p=retriever.retrieve(q,relation_mode="llm",search_mode="greedy",prefilter_mode=mode)
            d=p["relation_diagnostics"]
            if d["llm_called_pair_count"] or d["request_count"]: raise RuntimeError("cost sensitivity cache miss")
            pairs.append(len(d["prefilter_pairs"])); hits+=d["cache_hit_count"]; lookups+=d["cache_lookup_count"]
            rows.append(evaluate_prediction(p,gold_by_id[q["query_id"]],5))
        output[name]={"pairs_per_query":statistics.mean(pairs),**average(rows),"cache_hit_rate":hits/lookups,"new_http_requests":0}
    retriever.relation_scorer.pair_budget=original
    return output

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    ap.add_argument("--split",choices=("development","validation"),default="development"); args=ap.parse_args()
    raw=json.loads(args.config.read_text(encoding="utf-8")); stage3a,freeze,client,retriever=runtime(raw)
    output=ROOT/raw["output_dir"]; artifact=ROOT/raw["artifact_dir"]; queries,gold=load_inputs(args.split)
    ag_path=artifact/"type_agnostic_model.json"; aw_path=artifact/"type_aware_model.json"
    if args.split=="development" and not ag_path.exists():
        train,tune=group_split(queries,raw["seed"]); metadata={"bank_version":BANK_VERSION,"seed":raw["seed"]}
        ar,wr,labels,ast,_=collect_training(queries,gold,retriever,train)
        ag0,at=fit(ar,labels,raw,metadata); aw0,wt=fit(wr,labels,raw,metadata)
        tune_queries=[q for q in queries if str(q["chain_id"]) in tune]
        tune_metrics,tune_bank,_,_=evaluate(tune_queries,gold,retriever,ag0,aw0)
        selected=max(("learned_type_agnostic","learned_type_aware"),key=lambda x:(tune_metrics[x]["flow_complete_at_5"],tune_metrics[x]["complete_at_5"],x))
        all_groups=train|tune
        ar,wr,labels,ast,sizes=collect_training(queries,gold,retriever,all_groups)
        wst=dict(ast); ag,at2=fit(ar,labels,raw,metadata); aw,wt2=fit(wr,labels,raw,metadata)
        ag.save(ag_path); aw.save(aw_path)
        schema={"bank_version":BANK_VERSION,"agnostic_features":ag.feature_names,"aware_features":aw.feature_names,
                "forbidden":["gold","required_groups","required_flow_edges","query_id","chain_id","split","difficulty"]}
        write_json(artifact/"feature_schema.json",schema)
        summary={"python_version":platform.python_version(),"sklearn_version":sklearn.__version__,"seed":raw["seed"],
          "train_groups":len(train),"tune_groups":len(tune),"split_hash":digest({"train":sorted(train),"tune":sorted(tune)}),
          "tune_metrics":tune_metrics,"tune_bank":tune_bank,"selected_scorer":selected,"agnostic_training":ast,
          "aware_training":wst,"agnostic_fit_seconds":at2,"aware_fit_seconds":wt2}
        write_json(output/"training_summary.json",summary)
        devfreeze={"status":"FROZEN_AFTER_DEVELOPMENT","base_stage3a_commit":raw["base_stage3a_commit"],
          "candidate_bank_version":BANK_VERSION,"candidate_bank_top_m":raw["candidate_bank_top_m"],
          "candidate_bank_single_swap":True,"feature_schema_hash":digest(schema),"model_type":raw["model_type"],
          "model_hyperparameters":raw["model_hyperparameters"],"selected_scorer":selected,
          "training_group_split_hash":summary["split_hash"],"relation_prompt_version":freeze["relation_prompt_version"],
          "stage3a_proposer_model_hash":freeze["model_sha256"],"stage3a_pair_budget":freeze["pair_budget"],
          "search_pool_k":freeze["search_pool_k"],"seed":raw["seed"],
          "agnostic_model_hash":hashlib.sha256(ag_path.read_bytes()).hexdigest(),
          "aware_model_hash":hashlib.sha256(aw_path.read_bytes()).hexdigest()}
        write_json(output/"development_freeze.json",devfreeze)
    else:
        devfreeze=json.loads((output/"development_freeze.json").read_text(encoding="utf-8"))
        if devfreeze["base_stage3a_commit"]!=raw["base_stage3a_commit"]: raise RuntimeError("freeze mismatch")
    ag=LinearSetScorer.load(ag_path); aw=LinearSetScorer.load(aw_path)
    metrics,bank,cache,runtime_q=evaluate(queries,gold,retriever,ag,aw)
    sensitivity=cost_sensitivity(queries,gold,retriever)
    matrix={name:{"bank_oracle":bank["flow_complete_oracle"],"flow_complete":row["flow_complete_at_5"]} for name,row in metrics.items()}
    write_json(output/f"candidate_bank_{args.split}.json",bank); write_json(output/f"set_scorer_metrics_{args.split}.json",metrics)
    write_json(output/f"set_scorer_ablation_{args.split}.json",matrix)
    write_json(output/f"relation_selection_matrix_{args.split}.json",matrix)
    write_json(output/f"stage3a_cost_sensitivity_{args.split}.json",sensitivity)
    write_json(output/f"cache_diagnostics_{args.split}.json",cache); write_json(output/"config.json",raw)
    summary_path=output/"summary.json"; summary=json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
      "benchmark":"TEF_RAG_v6_temporal_hard_benchmark_v1","splits":{},"test_gold_accessed":False,
      "sealed_test_evaluator_accessed":False,"private_test_artifact_accessed":False,"target_method_test_runs":0,
      "benchmark_issue":"BENCHMARK_ISSUE_FOUND"}
    summary["splits"][args.split]={"candidate_bank":bank,"metrics":metrics,"ablation":matrix,"cost_sensitivity":sensitivity,
      "cache":cache,"rerank_runtime_per_query":runtime_q}; write_json(summary_path,summary)
    print(json.dumps(summary["splits"][args.split],ensure_ascii=False,indent=2))
if __name__=="__main__": main()
