# TEF-RAG v6 External Baseline Compatibility Audit

This audit inspected the official repositories and performed adapter-only smoke tests on three development queries. It did not run validation, test, or a formal baseline evaluation.

## 1. MRAG audit

- Official repository: [siyue-zhang/MRAG](https://github.com/siyue-zhang/MRAG), commit `19f3bcf9a365f9379e12edc13bec96c9ec557e1a` (upstream `master`, inspected 2026-09-17).
- License: MIT.
- Compatibility status: **BLOCKED** for formal v6 reproduction.

The paper's formal pipeline has three core modules: question processing; retrieval plus query-focused summarization/fine-grained sentence processing; and semantic-temporal hybrid ranking. The repository implements passage keyword ranking, semantic reranking, top-passage LLM summarization, sentence splitting/keyword ranking, and a final semantic score multiplied by a symbolic temporal coefficient. Summarization is therefore a core formal step, not an optional cosmetic output.

The released code defaults to a locally hosted Llama 3.1 instruction model through `vllm` for keyword extraction and query-focused summarization, with model choices including Llama 3.1 8B/70B. Substitution with this project's local LLM is methodologically reasonable only if the exact MRAG prompts and roles are retained, the substitute model is frozen before evaluation, and the deviation is reported. Omitting summarization or replacing the pipeline with BM25 plus decay is not MRAG.

The main compatibility blocker is question processing. The paper describes LLM decomposition into main content and temporal constraint, but the released `metriever.py` consumes a benchmark-provided `time_relation` string and then applies string/regex rules for relation type, years, months, and first/last intent. It does not expose a generic official decomposer for arbitrary queries. v6 has no corresponding deployment-visible annotation, and deriving it from benchmark construction metadata is forbidden.

MRAG temporal scoring consumes `time_relation_type` (`before`, `after`, `between`, or `other`), query year/month values, first/last intent, and years extracted from each sentence/summary. Evidence time is therefore a textual point date/year rather than a first-class interval. For v6, `event_time` can only be mapped as a point timestamp made visible to the official fine-grained processor; `available_at` remains a visibility cutoff and must not become event semantics. This mapping and the missing generic query decomposer must be frozen before MRAG can be called faithful.

Dependencies include Contriever or the released stage-one retrieval files, PyTorch, CUDA, `vllm`, NLTK sentence tokenization, SciPy, Transformers/SentenceTransformers or FlagEmbedding rerankers, a semantic reranker (the code defaults to NV-Embed-v2 for Metriever), and a Llama-family summarization model. No task-specific training is required, but several large pretrained models and GPU execution are required.

## 2. TA-RAG audit

- Official repository: [kwunhang/TA-RAG](https://github.com/kwunhang/TA-RAG), pinned/current upstream commit `9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9`.
- License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0).
- Compatibility status: **READY_WITH_ADAPTATION**.

The actual temporal entry point is `LLMClient.temporal_process_sentence()` in `experiment/src/tools/llm_response.py`. `ta_rag_retrieval()` calls it, validates a JSON result containing `rephrased_sentence` and `temporal_decomposition`, converts each interval to timestamps, filters document interval IDs with NCLS, creates monthly hypothetical queries over the requested interval, embeds those queries, and semantically ranks only temporal candidates with FAISS. An empty decomposition takes the full semantic-search branch.

The v5 result did not activate this mechanism. `NoEventIntervalParser` deliberately returned the original question with `temporal_decomposition=[]`; v5 also substituted the official Nomic 768-dimensional model/FAISS/NCLS stack with a shared 384-dimensional MiniLM, NumPy exact search, and an API-compatible linear interval implementation. It was correctly labeled a compatibility branch, not full TA-RAG.

For v6, each point `event_time` maps deterministically to `[event_time, event_time + 1 second)`, matching the official point-event handling. `query_time` defines the maximum visible snapshot and must also replace wall-clock `date.today()` when resolving relative expressions. The query's extracted temporal interval is a semantic target inside that already-safe snapshot; it must never enlarge visibility beyond `query_time`. A per-snapshot FAISS/NCLS index prevents future documents from influencing embeddings, graph/index structure, or candidate filtering.

TA-RAG does not require task-specific training. It requires `faiss`, `ncls`, NumPy, pandas, PyTorch, Transformers/SentenceTransformers, the `nomic-ai/nomic-embed-text-v1.5` model (768 dimensions), and an OpenAI-compatible LLM endpoint; the released configuration names `meta-llama/Llama-3.3-70B-Instruct`. The repository does not provide a ready-made v6 index or bundled model weights, so both must be downloaded/built for formal reproduction.

## 3. v6 field mapping

Adapters project raw benchmark records before invoking either method:

| v6 field | MRAG | TA-RAG |
|---|---|---|
| `query_text` | question input | `temporal_process_sentence` input |
| `query_time` | snapshot cutoff; relative-time anchor for adapted decomposer | snapshot cutoff and relative-time anchor |
| `asset_id` | optional fair corpus scope | optional fair corpus scope |
| evidence `text` | passage and sentence/QFS source | `chunk_text` |
| `event_time` | point date exposed to temporal sentence processing | one-second `event_time_interval` and document date |
| `available_at` | visibility only | visibility only |
| evidence ID | immutable passage provenance | `corpus_uid` and immutable provenance |

Only deployment-visible source/event metadata may be passed. `required_groups`, `required_flow_edges`, `allowed_endpoint_pairs`, FlowComplete labels, `chain_id`, difficulty, answer fields, and split construction metadata are rejected by the adapters.

## 4. Temporal leakage check

Both adapters first require `event_time <= query_time` and `available_at <= query_time`, then build the method-specific input. MRAG summaries must be generated per query from this snapshot; a summary cache may be keyed only by query plus snapshot hash. TA-RAG must build/load an index keyed by asset plus query-time snapshot hash. Building summaries, embeddings, FAISS, or NCLS over the full future corpus and filtering only final IDs is prohibited.

## 5. Provenance mapping

Every MRAG passage, split sentence, and generated summary carries the original `provenance_id`. Final sentence ranking is collapsed to the first occurrence of each original evidence ID. Every TA-RAG metadata row carries `corpus_uid == provenance_id == original evidence ID`. Mapping preserves official rank order, removes duplicates, rejects IDs outside the visible snapshot, and truncates deterministically to five. No gold is used; fewer than five outputs are allowed only when the official backend or visible corpus returns fewer candidates.

## 6. Dependencies and runtime

The third-party repositories were cloned only under ignored `experiments/runtime/`; no upstream source, model, cache, or key is committed. The current audit environment lacks MRAG's `vllm`/reranker stack and TA-RAG's FAISS, NCLS, SentenceTransformers, Nomic model, and configured LLM endpoint. Therefore this audit did not claim an official end-to-end runtime success.

## 7. Minimal smoke result

Four adapter tests pass. Three development queries were projected without reading development gold; for both adapters the fake official-backend boundary received only visible evidence and deterministically returned five original IDs. Future-event and future-availability records were excluded, forbidden fields were rejected, duplicate/out-of-snapshot provenance was removed, and TA point intervals were one second wide. Validation and test were not opened.

## 8. Reproduction recommendation

1. **TA-RAG — READY_WITH_ADAPTATION:** proceed to formal reproduction after pinning/installing FAISS/NCLS/Nomic/LLM dependencies, binding relative time to `query_time`, and building per-snapshot indexes. The official temporal mechanism has a clear callable entry point.
2. **MRAG — BLOCKED:** do not start formal scoring until a frozen, paper-consistent generic question-decomposition protocol is specified and the required GPU LLM/reranker stack passes an official end-to-end smoke. The summarization and hybrid ranking modules must remain intact.
