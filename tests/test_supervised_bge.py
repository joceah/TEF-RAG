from scripts import run_supervised_bge as baseline


def test_document_labels_include_all_acceptable_ids_and_top_bm25_negatives(monkeypatch):
    query = {"query_id": "q", "query_text": "question"}
    evidence = [{"evidence_id": name, "text": name} for name in ("p1", "p2", "n1", "n2", "n3")]
    ranked = [{"evidence_id": name} for name in ("n1", "p1", "n2", "p2", "n3")]
    monkeypatch.setattr(baseline, "bm25_rank", lambda *_args: ranked)
    gold = {"required_groups": [{"acceptable_evidence_ids": ["p1", "p2"]}],
            "required_flow_edges": [{"relation_type": "irrelevant_to_training"}]}

    pairs, counts = baseline.training_pairs([query], evidence, [gold], negatives_per_query=2)

    assert {(text, label) for _, text, label in pairs} == {
        ("p1", 1.0), ("p2", 1.0), ("n1", 0.0), ("n2", 0.0),
    }
    assert counts == {"positive": 2, "negative": 2, "queries_without_eligible_positive": 0}
