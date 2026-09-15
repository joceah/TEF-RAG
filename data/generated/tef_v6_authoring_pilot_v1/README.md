# TEF-RAG v6 Authoring Pilot v1

This public dataset is a 16-chain semantic-authoring pilot, not a benchmark release or split. Its status is `AUTHORING_PILOT_UNREVIEWED`; review status is `PENDING_USER_AND_CHATGPT_REVIEW`.

Operational semantics, evidence prose, queries, acceptable alternatives, and canonical flows were authored directly in `authoring/pilot_authored_chains.jsonl`. Python only assigns IDs, normalizes/serializes records, validates structure and produces the review book. No retrieval baseline was run and no v6 implementation is included.

The previous rule-generated candidate was discarded because semantic generation was template-driven and did not faithfully instantiate Temporal Evidence Flow.
