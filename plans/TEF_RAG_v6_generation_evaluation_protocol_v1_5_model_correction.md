# TEF-RAG v6 Generation Evaluation Protocol v1.5 Model Correction

Status: frozen before any new formal generation, scoring, or private-gold access.

The v1.4 formal generation attempt stopped before completion after a runtime JSON parse failure. It produced one partial prediction row per method, did not freeze, did not evaluate, and did not access private generation gold or its index. The diagnostic request used the legacy `deepseek-chat` model ID; the official response envelope identified the current Flash service and the malformed assistant content had one trailing `}`.

Before any new generation scoring or private access, the downstream generator is fixed to DeepSeek's current official canonical model ID `deepseek-flash` at `https://api.deepseek.com/chat/completions`, with temperature 0, JSON-object response format, and one repair maximum. The previous partial predictions and cache belong to the aborted v1.4 session and must not be reused by the new session.

This correction is based on runtime/provenance diagnostics before formal scoring. It does not use generation metrics or private gold. It does not change retrieval outputs, generator prompt text, schema, metric definitions, canonicalization, or repair policy. The new formal session binds model, endpoint, runner, prompt, schema, protocol version, and sealed retrieval prediction hashes; rows from a different session fail closed and must be archived outside the repository.
