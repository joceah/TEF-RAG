# TEF-RAG v6 Generation Evaluation Protocol v1.6 Non-Thinking Runtime Clarification

Status: frozen before any new formal generation, scoring, or private-gold access.

After v1.5, no new formal generation had started. There was exactly one non-formal smoke diagnostic, which was never added to predictions. It did not freeze, evaluate, or access private generation gold or its index. The smoke response showed that `deepseek-flash` defaulted to thinking: 4,673 of 5,000 completion tokens were reasoning tokens, `finish_reason=length`, and the visible JSON was truncated.

Thinking mode also means the registered `temperature=0` setting is not effective for the downstream generation configuration. Before any new formal generation, scoring, or private access, the request explicitly sets `thinking={"type":"disabled"}`. The canonical model remains `deepseek-flash` at `https://api.deepseek.com/chat/completions`, with temperature 0, max tokens 5000, JSON-object response format, and one repair maximum.

This is an API runtime compatibility correction before formal scoring. It does not use generation metrics or private gold and does not change the model identity, endpoint, prompt, schema, canonicalization, retrieval outputs, metrics, or repair policy. The protocol, model, thinking mode, endpoint, request configuration, runner, prompt, schema, registries, and sealed retrieval hashes are bound into session and provenance fingerprints. A `finish_reason=length` response is an incomplete transport failure and is retried by the existing transport policy; it is never passed to schema repair or saved as a prediction. JSON parsing remains strict and no malformed-JSON repair is added.
