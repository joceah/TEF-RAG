# TEF-RAG v6 Generation Evaluation Protocol v1.4 Short Retrieval Output Clarification

Status: frozen before any formal generation, API, or private-gold access. This is a protocol-consistency correction based only on the already public and sealed retrieval predictions. It does not use generation-test results or private gold and does not change generation metrics.

“Top-5” denotes the retrieval budget upper bound `k=5`; it does not require every method/query to fill five records. The downstream generator receives exactly the frozen `selected_evidence_ids` for that method/query, which may contain 0–5 unique visible evidence records.

Short or empty retrieval output is part of the retrieval method outcome. It must not be padded, replaced, rerun, or supplemented with other evidence. No retrieval output, generator prompt, schema, canonicalization, repair policy, or metric definition changes under this clarification.
