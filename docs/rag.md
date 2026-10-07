# RAG

`ingest → parse → chunk → embed → upsert (Qdrant) → register (knowledge_docs) → retrieve → rerank → build context → grounded generation`.

- **Documents:** `.md`, `.txt`, `.json`, `.pdf` (<=5 MB). Markdown front-matter supplies metadata. Types: past_project, historical_quote, specification, material, pricing, contractor, policy, design_guideline, faq, customer_profile.
- **Chunking:** paragraph-aware, `RAG_CHUNK_CHARS` (900) with `RAG_CHUNK_OVERLAP` (120); each chunk is prefixed with the document title.
- **Metadata (payload):** `doc_id, doc_type, category, room_type, location, budget_range, material_type, project_id, date, source, title, customer_email, is_sample`. Keyword payload indexes are created on remote Qdrant.
- **Ids:** `uuid5(doc_id:chunk_index)`, so re-ingesting a document replaces its chunks.
- **Embeddings:** `Embedder` interface. `hash` (dependency-free, deterministic, lexical; for dev/CI) and `sentence_transformers` (semantic; needs `requirements-ml.txt`; untested here). The collection's vector size must match the embedder or startup raises an actionable error.
- **Retrieval:** vector search (`RAG_CANDIDATE_K`=18) → rerank (0.70 vector + 0.25 lexical overlap + metadata boosts for category/room/location) → top `RAG_TOP_K`=6. Filters: `doc_type`, `category`, `customer_email`, ...
- **Returning clients:** a second, filtered retrieval pulls that client's `customer_profile` chunks (by e-mail).
- **Context safety:** every chunk is wrapped in `<untrusted_document id=... type=...>`; chunks that match injection heuristics are listed in the evidence panel as excluded and never reach the model; total context is capped (`RAG_CONTEXT_MAX_CHARS`).
- **Grounding:** the planner may cite `evidence_ids`; the narrative may reference only provided titles. The model is told not to invent past projects, and the UI shows exactly which documents were retrieved.
- **Degraded mode:** if Qdrant is unreachable the quote continues without evidence and carries a `retrieval_degraded` flag.
- **Quality:** `tests/evals/test_evals.py` asserts recall@6 on 8 queries and MRR >= 0.6 for the sample corpus (hash embedder).
