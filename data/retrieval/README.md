# Retrieval benchmark

The retrieval benchmark contains 400 event chains, 3,888 evidence records, 1,200 task intents, and 2,400 queries.

- benchmark/ contains queries, evidence, chain descriptions, development/validation references, and the released 480-query test evaluator.
- predictions/ contains published test predictions for BM25, BGE Reranker, Temporal-BM25, TA-RAG, and TEF-RAG.
- benchmark/metadata/ contains the relation taxonomy, source registry, and split summary.

The test evaluator was withheld during model development and released after the reported evaluation.

~~~bash
python -m scripts.validate_public_retrieval
python -m scripts.evaluate_public_retrieval
~~~
