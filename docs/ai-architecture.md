# AI architecture

## Where AI is used, and where it is not

| Step | Technique | Model tier | Deterministic guard |
|---|---|---|---|
| Photo analysis | Multimodal LLM + Pillow/NumPy measurements | medium | `sanitize_vision` clamps dimensions to "estimated", caps confidence, adds limitations |
| Requirement extraction | LLM, forced structured output (Pydantic) | medium | Known client facts override; `missing_information` recomputed in code |
| Project classification | LLM + keyword cross-check | simple | Unknown category falls back to keywords |
| Clarification questions | LLM | simple | Template fallback if output invalid |
| Scope planning (materials, quantities) | **Tool-using agent** (`material_lookup`, `project_similarity_search`) with RAG context | complex | Unknown groups dropped, duplicates merged, units corrected, quantity outliers flagged, default scope if output invalid |
| **Pricing, timeline, tiers** | **No LLM** | n/a | `pricing/engine.py`, `pricing/timeline.py` |
| Budget negotiation | LLM only parses the client's constraint; **`pricing/fitter.py` recalculates** | medium | Every step and saving is recorded |
| Quote narrative | LLM, structured | complex | Amounts must match engine output, else replaced and flagged |
| Recommendations | LLM | medium | Optional; failure skips the step |
| Chat routing and Q&A | LLM intent classifier; grounded Q&A | simple / medium | Q&A sees only stored quote facts |

## Model routing

`llm/router.py` maps a task to a tier and a tier to a model id read from settings (`LLM_MODEL_SIMPLE/MEDIUM/COMPLEX`). No model id is hard-coded in agent code.
Override per task with `LLM_TASK_TIER_OVERRIDES`. If a model is unavailable (or rejects the request with 400/404) and `LLM_FALLBACK_ENABLED=true`, the client retries on the next cheaper tier; every attempt is logged to `llm_calls`.
Switching provider is configuration: `LLM_PROVIDER=anthropic | openai | mock`. The OpenAI-compatible provider also targets local servers (vLLM, Ollama) via `OPENAI_BASE_URL`; set the three tier model names to local models.
Only the minimal request surface is sent (model, max_tokens, system, messages, tools, tool_choice); sampling parameters are deliberately omitted because some current models restrict them. Model ids and availability change: **verify them against Anthropic's models page before deploying.**

## Structured output and validation

`LLMClient.structured` forces a tool call whose JSON schema is the Pydantic model, validates the result, and on failure returns the validation error to the model for **one** retry (`LLMOutputError` afterwards). `run_agent` runs a bounded tool loop (max 6 steps, then forces the final answer).

## Tool boundary

`tools/registry.py` is the only way a model can act. Arguments are validated against typed models; tools run with a timeout; results are wrapped as untrusted data.
Model-callable tools are read-only. `quote_store`, `project_store`, `crm_create_lead`, `crm_lookup`, `customer_lookup` and `notify` are application-only: the model cannot even see them, and the registry rejects them if requested (tested).

## Prompt-injection defences (`llm/safety.py`)

1. Client text, retrieved documents and tool output are wrapped in `<untrusted_*>` delimiters; delimiter look-alikes inside them are neutralised.
2. A system guard tells the model never to obey that content and never to invent prices, measurements, availability or history.
3. A heuristic scanner flags override/role-hijack/exfiltration/approval-bypass patterns. Flagged client input forces human approval; flagged retrieved chunks are **excluded** from the model context.
4. Even a fully successful injection cannot change a price (pricing is code), skip approval (policy is code), or call a write tool (not exposed). Evaluated in `tests/evals`.
The scanner is heuristic and will miss novel phrasings; the structural controls above are the real defence.

## Vision pipeline

Upload → decode with Pillow (format allow-list JPEG/PNG/WebP, pixel and size limits), EXIF stripped by re-encoding → stored → `vision/cv.py` measures resolution, brightness, contrast, sharpness, dominant palette, colour temperature and quality flags → multimodal model returns `RoomVisionAnalysis` (each attribute carries provenance `detected | estimated | user_provided | unknown` and confidence) → sanitised.
Object detection is a pluggable `ObjectDetector`: set `CV_DETECTOR_MODEL` (YOLO weights; needs `requirements-ml.txt`) to enable it. With no detector configured the UI says so and no detections are fabricated. **The YOLO path is not exercised by the test-suite.**
A photo-derived area is only a hint: it never satisfies the "floor area" requirement.

## Deterministic pricing

```
line     = (qty x unit_price + qty x labour_hours x hourly_rate x complexity) x regional_multiplier
subtotal = sum(lines) + logistics% x materials
total    = (subtotal + contingency% x subtotal) x (1 + tax%)
```
Decimal arithmetic, half-up to 2 places at each reported figure, so components add up exactly (tested). Complexity (`low|standard|high|rush`) comes from stated constraints, visible issue severity, room count and a compressed timeline. Catalog, labour rates and regions live in the database (editable by admins) and are **sample data** until you replace them.
Timeline: labour hours per phase / (crew x 8 h), phases in sequence, plus any material lead time that exceeds the time before its phase starts, plus 10% buffer.

## Negotiation

`negotiation_parse` (LLM) extracts the new budget and what to keep or drop → `negotiation_refit` (code) removes requested items, then repeatedly takes the downgrade with the best saving per unit of "importance", then drops optional lines, until the budget is met or nothing is left to change → `retrieve_alternatives` → narrative → validation → new version `n+1` (selected option `fitted`). If the budget cannot be met, the quote says so and shows the minimum achievable total.

## Confidence

`0.35 x requirement completeness + 0.20 x vision confidence + 0.20 x retrieval support + 0.25 x scope quality`, x0.8 if the area was assumed. It is a heuristic for triage, not a calibrated probability.

## Workflow diagram

Generated from the compiled graph: [workflow-graph.md](workflow-graph.md).
