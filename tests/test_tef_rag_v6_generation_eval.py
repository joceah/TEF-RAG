from __future__ import annotations

from tef_rag_v6.generation_eval import Canonicalizer, evaluate_generation_prediction, validate_generation_output


def schema():
    return {
        "type":"object","additionalProperties":False,"required":["work_order","action_plan"],
        "properties":{
            "work_order":{"type":"object","additionalProperties":False,
                "required":["asset_id","diagnosis","recommended_actions","applicable_procedure","verification_or_uncertainty","supporting_evidence_ids"],
                "properties":{
                    "asset_id":{"type":"string"},
                    "diagnosis":{"type":"object","additionalProperties":False,"required":["status","concept","supporting_evidence_ids"],"properties":{"status":{"type":"string"},"concept":{"type":["string","null"]},"supporting_evidence_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True}}},
                    "recommended_actions":{"type":"array","items":{"type":"string"},"uniqueItems":True},
                    "applicable_procedure":{"type":"object","additionalProperties":False,"required":["status","procedure_version","supporting_evidence_ids"],"properties":{"status":{"type":"string"},"procedure_version":{"type":["string","null"]},"supporting_evidence_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True}}},
                    "verification_or_uncertainty":{"type":"object","additionalProperties":False,"required":["status","statement","supporting_evidence_ids"],"properties":{"status":{"type":"string"},"statement":{"type":["string","null"]},"supporting_evidence_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True}}},
                    "supporting_evidence_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True},
                }},
            "action_plan":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["action_id","action_type","target","parameters","depends_on","supporting_evidence_ids"],"properties":{"action_id":{"type":"string"},"action_type":{"type":"string"},"target":{"type":["string","null"]},"parameters":{"type":"object"},"depends_on":{"type":"array","items":{"type":"string"},"uniqueItems":True},"supporting_evidence_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True}}}}
        }
    }


def canon():
    return Canonicalizer(
        {"status_aliases":{"confirmed":["确认"],"pending":["待验证"],"not_applicable":[]},"action_type_aliases":{"repair":["修复"],"verify":["复测"]}},
        {"aliases":{},"numeric_tolerance":1e-6},
    )


def gold():
    return {
        "work_order":{
            "asset_id":"Rack-A",
            "diagnosis":{"status":"confirmed","concept":"fan failure","supporting_evidence_ids":["E1"]},
            "recommended_actions":["A1"],
            "applicable_procedure":{"status":"not_applicable","procedure_version":None,"supporting_evidence_ids":[]},
            "verification_or_uncertainty":{"status":"pending","statement":"verify after repair","supporting_evidence_ids":["E2"]},
            "supporting_evidence_ids":["E1","E2"],
        },
        "action_plan":[
            {"action_id":"A1","action_type":"repair","target":"cooling fan","parameters":{},"depends_on":[],"supporting_evidence_ids":["E1"]},
            {"action_id":"A2","action_type":"verify","target":"temperature","parameters":{},"depends_on":["A1"],"supporting_evidence_ids":["E2"]},
        ],
    }


def test_exact_semantic_plan_scores_one_even_when_action_ids_differ():
    g=gold(); p=gold()
    p["action_plan"][0]["action_id"]="X"; p["action_plan"][1]["action_id"]="Y"
    p["action_plan"][1]["depends_on"]=["X"]; p["work_order"]["recommended_actions"]=["X"]
    values=evaluate_generation_prediction(p,g,schema(),canon(),{"E1","E2"},"Rack-A")
    assert values["work_order_em_strict"] == 1
    assert values["action_f1"] == 1
    assert values["dependency_f1"] == 1
    assert values["plan_em_strict"] == 1
    assert values["citation_f1"] == 1
    assert values["task_success"] == 1


def test_missing_action_is_penalized():
    g=gold(); p=gold()
    p["action_plan"]=p["action_plan"][:1]
    p["work_order"]["supporting_evidence_ids"]=["E1","E2"]
    values=evaluate_generation_prediction(p,g,schema(),canon(),{"E1","E2"},"Rack-A")
    assert values["action_recall"] == 0.5
    assert values["plan_em_strict"] == 0
    assert values["task_success"] == 0


def test_top_citation_union_and_context_citations_are_validated():
    p=gold(); p["work_order"]["supporting_evidence_ids"]=["E1"]
    errors=validate_generation_output(p,schema(),{"E1","E2"},"Rack-A")
    assert "top citation union mismatch" in errors
    p=gold(); p["action_plan"][0]["supporting_evidence_ids"]=["E99"]
    p["work_order"]["supporting_evidence_ids"]=["E1","E2","E99"]
    errors=validate_generation_output(p,schema(),{"E1","E2"},"Rack-A")
    assert any("citation outside supplied evidence" in error for error in errors)


def test_wrong_claim_text_does_not_receive_citation_credit():
    g=gold(); p=gold(); p["work_order"]["diagnosis"]["concept"]="different diagnosis"
    values=evaluate_generation_prediction(p,g,schema(),canon(),{"E1","E2"},"Rack-A")
    assert values["citation_f1"] < 1
    assert values["task_success"] == 0
