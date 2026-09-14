from baseline_adapters.tg_rag_source_v2 import context_text, source_ids


def test_recovers_ids_from_plain_context():
    raw = "record_id: doc-a\ncontent: x\nrecord_id: doc-b\n"
    assert source_ids(raw) == ["doc-a", "doc-b"]


def test_recovers_ids_from_official_context_tuple():
    raw = ("record_id: doc-a\ncontent: x\nrecord_id: doc-a\n", {"total_evidence": 2})
    assert context_text(raw).startswith("record_id: doc-a")
    assert source_ids(raw) == ["doc-a"]


def test_rejects_unknown_result_shape():
    try:
        source_ids({"context": "record_id: doc-a"})
    except TypeError as exc:
        assert "unsupported TG-RAG context result" in str(exc)
    else:
        raise AssertionError("unknown result shape must fail closed")
