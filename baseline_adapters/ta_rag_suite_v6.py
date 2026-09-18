"""Finite TEF-v6 compatibility layer around the frozen official TA-RAG mechanism."""
from __future__ import annotations

from datetime import date, datetime, timezone
import calendar
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from tef_rag_v6.baseline_suite import map_provenance, point_interval, visible_snapshot


UPSTREAM_COMMIT = "9e5e28a9e7ddad7d6d022c4d3533dbca2aff03b9"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"


class _FrozenDate(date):
    value = date(1970, 1, 1)

    @classmethod
    def today(cls):
        return cls.value


class TARAGRuntime:
    """Official parser + NCLS filtering + Nomic embeddings + FAISS ranking."""

    def __init__(self, upstream: str | Path, base_url: str, api_key: str, model: str,
                 embedding_path: str | Path | None = None, reranker_path: str | Path | None = None):
        if not api_key:
            raise RuntimeError("TA_RAG_API_KEY must be supplied at runtime and is never persisted")
        try:
            import faiss
            from ncls import NCLS
            import torch
            from sentence_transformers import CrossEncoder, SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(f"official TA-RAG dependency unavailable: {exc}") from exc
        self.faiss, self.NCLS = faiss, NCLS
        source = Path(upstream) / "experiment" / "src"
        if not source.exists():
            raise RuntimeError(f"frozen TA-RAG checkout missing: {source}")
        sys.path.insert(0, str(source))
        self.llm_module = importlib.import_module("tools.llm_response")
        self.client = self.llm_module.LLMClient(base_url, api_key, model)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.embedder = SentenceTransformer(str(embedding_path or EMBEDDING_MODEL),
                                            trust_remote_code=True, device=device)
        if not reranker_path:
            raise RuntimeError("official TA-RAG BGE reranker path is required")
        self.reranker = CrossEncoder(str(reranker_path), trust_remote_code=True, device=device)
        self._embedding_cache: dict[str, np.ndarray] = {}
        self._last_request_at: float | None = None
        self.cache_path = Path(upstream).parent / "cache" / "ta_rag_parser.json"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._parser_cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}

    def _parse(self, query: dict) -> dict:
        cache_key = f"{query['query_time']}\n{query['query_text']}"
        if cache_key in self._parser_cache:
            return self._parser_cache[cache_key]
        reference = datetime.fromisoformat(query["query_time"].replace("Z", "+00:00")).date()
        _FrozenDate.value = reference
        original = self.llm_module.date
        completions = self.client.openai_client.chat.completions
        original_create = completions.create
        def frozen_create(*args, **kwargs):
            kwargs["temperature"] = 0
            # The local relay is deliberately single-flight.  Keep every
            # official parser attempt serial and at least four seconds apart;
            # retry transient Busy responses here because upstream's exception
            # logger references an unset response object on transport errors.
            for attempt in range(5):
                if self._last_request_at is not None:
                    time.sleep(max(0.0, 4.0 - (time.monotonic() - self._last_request_at)))
                self._last_request_at = time.monotonic()
                try:
                    response = original_create(*args, **kwargs)
                    content = response.choices[0].message.content or ""
                    # Upstream slices from its misspelled ``json fence marker.
                    # Official DeepSeek commonly returns bare JSON, so provide
                    # only the expected envelope without changing the payload.
                    if "``json" not in content and "{" in content and "}" in content:
                        response.choices[0].message.content = f"```json\n{content}\n```"
                    return response
                except Exception as exc:
                    if "429" not in str(exc) and "Busy" not in str(exc):
                        raise
                    if attempt == 4:
                        raise
        self.llm_module.date = _FrozenDate
        completions.create = frozen_create
        try:
            result = self.client.temporal_process_sentence(query["query_text"], chance=5)
        finally:
            self.llm_module.date = original
            completions.create = original_create
        if not result:
            raise RuntimeError("official temporal_process_sentence failed after 5 attempts")
        self._parser_cache[cache_key] = result
        self.cache_path.write_text(json.dumps(self._parser_cache, ensure_ascii=False), encoding="utf-8")
        return result

    @staticmethod
    def _stamp(value: str, query_time: str) -> int:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.fromisoformat(query_time.replace("Z", "+00:00")).tzinfo)
        return int(parsed.timestamp())

    def _embed_documents(self, rows: list[dict]) -> np.ndarray:
        missing = [row for row in rows if row["evidence_id"] not in self._embedding_cache]
        if missing:
            texts = [f"search_document: {row['text']}" for row in missing]
            vectors = self.embedder.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
            self._embedding_cache.update((row["evidence_id"], vector.astype("float32"))
                                         for row, vector in zip(missing, vectors))
        return np.stack([self._embedding_cache[row["evidence_id"]] for row in rows]).astype("float32")

    def retrieve(self, query: dict, evidence: list[dict], top_k: int = 5) -> list[str]:
        rows = visible_snapshot(query, evidence)
        if not rows:
            return []
        analysis = self._parse(query)
        starts, ends = zip(*(point_interval(row["event_time"]) for row in rows))
        ids = np.arange(len(rows), dtype=np.int64)
        tree = self.NCLS(np.asarray(starts, dtype=np.int64), np.asarray(ends, dtype=np.int64), ids)
        intervals = analysis["temporal_decomposition"]
        candidates: set[int] = set()
        for interval in intervals:
            begin = self._stamp(interval["begin"], query["query_time"])
            end = self._stamp(interval["end"], query["query_time"]) + 1
            candidates.update(int(match[2]) for match in tree.find_overlap(begin, end))
        if intervals and not candidates:
            return []
        candidate_ids = sorted(candidates) if intervals else list(range(len(rows)))
        vectors = self._embed_documents(rows)
        index = self.faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        hypothetical = []
        for interval in intervals:
            begin = datetime.fromtimestamp(self._stamp(interval["begin"], query["query_time"]), tz=timezone.utc)
            end = datetime.fromtimestamp(self._stamp(interval["end"], query["query_time"]), tz=timezone.utc)
            cursor = datetime(max(begin.year, 2012), begin.month if begin.year >= 2012 else 1, 1, tzinfo=timezone.utc)
            while cursor <= end:
                hypothetical.append(f"search_query: In {calendar.month_name[cursor.month]} {cursor.year}, {analysis['rephrased_sentence']}")
                cursor = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1, tzinfo=timezone.utc)
        if not hypothetical:
            hypothetical = [f"search_query: {analysis['rephrased_sentence']}"]
        query_vectors = self.embedder.encode(hypothetical, normalize_embeddings=True,
                                             convert_to_numpy=True).astype("float32")
        query_vector = np.mean(query_vectors, axis=0, keepdims=True).astype("float32")
        semantic_k = min(top_k * 20, len(candidate_ids))
        if len(candidate_ids) == len(rows):
            scores, ranked = index.search(query_vector, semantic_k)
            order = [int(value) for value in ranked[0] if value >= 0]
        else:
            scores = vectors[candidate_ids] @ query_vector[0]
            order = [candidate_ids[i] for i in sorted(range(len(candidate_ids)),
                     key=lambda i: (-float(scores[i]), rows[candidate_ids[i]]["evidence_id"]))[:semantic_k]]
        rerank_scores = self.reranker.predict([[query["query_text"], rows[i]["text"]] for i in order],
                                               batch_size=16, show_progress_bar=False)
        order = [item[0] for item in sorted(zip(order, rerank_scores),
                 key=lambda item: (-float(item[1]), rows[item[0]]["evidence_id"]))[:top_k]]
        ranked_rows = [{"provenance_id": rows[i]["evidence_id"]} for i in order]
        return map_provenance(ranked_rows, [row["evidence_id"] for row in rows], top_k)
