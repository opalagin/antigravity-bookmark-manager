# OpenAI Embeddings Provider — Specification

Status: Draft
Author: brainstorm with Claude
Date: 2026-05-20

## 1. Goal

Add OpenAI's embedding API as a second, **pluggable** embedding backend for the Search Backend, while keeping the current local `fastembed` (BAAI/bge-small-en-v1.5) implementation fully supported. The local path remains the default for on-prem / self-hosted / offline deployments; OpenAI becomes the default for hosted (Railway) deployments where idle RAM cost of the local ONNX model is the dominant operating expense.

This is **not** a swap. Both providers ship in the same image and are selected at runtime by configuration.

## 2. Motivation

- The local embedding model is the single largest source of resident memory in the Search Backend container (see `Docs/Internals` memory roadmap and the May 17 profiling notes). Idle RSS on Railway is ~2 GB, primarily from ONNX Runtime + numpy buffers held by `fastembed`.
- OpenAI `text-embedding-3-small` is priced at ~$0.02 / 1M tokens. For a single-user pilot at typical bookmark sizes (few thousand bookmarks, ~1–5 k tokens each, re-embedded rarely), monthly embedding cost is on the order of cents — far below the marginal Railway memory cost.
- Offloading inference to OpenAI lets us drop the embedding model from the container entirely in hosted mode, unblocking a much smaller base image and lower Railway plan tier.

## 3. Non-goals

- Not changing the chat / LLM path. `SearchService.chat` already uses OpenAI (`services.py:209-270`) and is unaffected.
- Not introducing per-user provider selection in v1. Provider is a deployment-wide setting.
- Not supporting concurrent dual-provider corpora for a single deployment. Switching providers requires a one-time re-embed.
- Not introducing a third provider (Cohere, Voyage, local Ollama embeddings, etc.). The abstraction should make that possible later, but only two implementations ship now.
- Not adding a migration tool that converts existing vectors between providers — vectors from different models are not comparable, the only correct migration is re-embed from `content_markdown`.

## 4. Current state (reference)

Single embedding code path, no provider abstraction:

- `Search Backend/services.py:50-70` — `EmbeddingService` constructs `TextEmbedding("BAAI/bge-small-en-v1.5", threads=1)` at module import. Model loads eagerly into the singleton `embedding_service`.
- `Search Backend/services.py:58-67` — `embed_documents(texts)` and `embed_query(text)` are the only two public entry points. Both offload to a thread via `asyncio.to_thread`.
- `Search Backend/services.py:111` (ingest) and `services.py:137` (search) and `services.py:456` (re-embed) are the three call sites.
- `Search Backend/models.py:39` — `embedding: List[float] = Field(sa_column=Column(Vector(384)))`. The 384 is the BGE-small dimension and is hard-coded.
- `Search Backend/main.py:116` — schema bootstrap SQL also hard-codes `VECTOR(384)` and creates an HNSW index `embedding_idx` with `vector_cosine_ops`.
- `Search Backend/requirements.txt` — `fastembed==0.4.2`, `openai==1.63.2` already present (OpenAI is currently used only for chat).
- `Search Backend/services.py:30-37` — `_get_openai_client()` already memoizes an `AsyncOpenAI` keyed off `OPENAI_API_KEY`. Reuse it.

## 5. Design

### 5.1 Provider abstraction

Introduce a thin `EmbeddingProvider` protocol/ABC in `services.py` (or a new `embeddings.py`):

```python
class EmbeddingProvider(Protocol):
    name: str              # "local" | "openai"
    dimension: int         # vector size produced by this provider
    table_name: str        # pgvector table this provider's vectors live in

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Two concrete implementations:

1. **`LocalEmbeddingProvider`** — wraps existing `fastembed` code unchanged. Model load moves from module-import time into `__init__` of this class only, so it is **only constructed when selected**. Today it is constructed unconditionally as a module-level singleton, which is what we want to stop doing.
   - `name = "local"`, `dimension = 384`, `table_name = "bookmark_embeddings"` (keeps existing schema and data).
2. **`OpenAIEmbeddingProvider`** — uses `AsyncOpenAI.embeddings.create`.
   - Default model: `text-embedding-3-small`.
   - Default dimension: `1536` (native). Configurable via `OPENAI_EMBEDDING_DIMENSIONS` (OpenAI supports Matryoshka-style truncation via the `dimensions` parameter; valid values 256–1536 for `-small`, up to 3072 for `-large`).
   - `table_name = "bookmark_embeddings_openai"`.
   - Batching: pass the full chunk list straight through. OpenAI accepts up to 2048 inputs and 8191 tokens per input per call; current chunk size (1000 chars with 200 overlap, `services.py:39-47`) is well below that.
   - Retry: wrap calls with bounded exponential backoff on `RateLimitError` and `APIConnectionError` (3 retries, 1s/2s/4s, jittered).
   - Query embedding: no prefix tweaks — OpenAI does not have a separate query encoder.

A single module-level `get_provider()` resolves the active provider once per process based on env (see 5.4) and caches it.

### 5.2 Schema — per-provider tables (recommended option B)

OpenAI embeddings are not the same dimensionality as BGE, and pgvector columns are dimension-typed. We considered three options:

- **A. Extra column on the existing table.** Add `embedding_openai VECTOR(1536)` alongside `embedding VECTOR(384)`. Half the rows NULL on either side, two indexes on the same table. Simple, but encodes "two providers" forever and is awkward if a third is added.
- **B. Per-provider table.** New table `bookmark_embeddings_openai` with `VECTOR(1536)`, FK to `bookmarks`, identical structure otherwise. Search/ingest pick the table based on the active provider. **Recommended.** Cleaner, scales to additional providers, and the unused table simply stays empty in deployments that never enable it.
- **C. Reduce OpenAI to 384.** Pass `dimensions=384` to OpenAI so it fits the existing column. Discards quality, hard to revisit later. Rejected.

Adopt **B**.

New table (created idempotently in `main.py` `lifespan`, same pattern as today):

```sql
CREATE TABLE IF NOT EXISTS bookmark_embeddings_openai (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536)
);
CREATE INDEX IF NOT EXISTS embedding_openai_idx
    ON bookmark_embeddings_openai USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_bookmark_embeddings_openai_bookmark_id
    ON bookmark_embeddings_openai(bookmark_id);
```

Model layer:

- Add `BookmarkEmbeddingOpenAI` in `models.py` mirroring `BookmarkEmbedding` but with `Vector(1536)` and the new tablename.
- The `Bookmark.embeddings` relationship is kept on the original (local) table; a parallel `embeddings_openai` relationship is added. Cascade-delete continues to work via FK.

If the configured OpenAI dimension is anything other than 1536, the deployment must use a different table or accept a schema rebuild. Treat 1536 as the canonical size for v1 — document `OPENAI_EMBEDDING_DIMENSIONS` as an advanced override that requires manual schema work.

### 5.3 Service wiring

- `IngestionService.process_bookmark` (`services.py:78`) — replace direct use of `BookmarkEmbedding` with a helper that takes the active provider, picks the right SQLModel class, and inserts there. The chunking logic (`split_text`) stays shared; only the model class and `embed_documents` call vary.
- `SearchService.search` (`services.py:135`) — same idea: select from the table associated with the active provider. The cosine-distance threshold (`services.py:165-166`, currently `0.4` tuned for BGE) is **provider-specific** because absolute distance ranges differ between models. Make `threshold` a property of the provider, defaulted per provider:
  - Local (BGE-small): `0.4` (unchanged).
  - OpenAI (`text-embedding-3-small`): start at `0.6` — OpenAI's normalized embeddings produce distances in a wider band. Tune empirically against a small evaluation set before flipping the production default.
- `SearchService.chat` — only consumes `search` results; no change needed beyond what `search` provides.
- `ManagementService.reembed_user_bookmarks` (`services.py:426`) — already streams per bookmark and deletes-then-inserts. Update to delete from and insert into the active provider's table, not a hard-coded one. Becomes the migration tool when flipping providers.

### 5.4 Configuration

Environment variables (read at startup, treated as immutable for the process):

| Name | Values | Default | Effect |
|---|---|---|---|
| `EMBEDDING_PROVIDER` | `local` \| `openai` | `local` | Which provider to construct. Anything else → startup error. |
| `OPENAI_API_KEY` | string | unset | Required iff provider is `openai`. Reuses existing key already used for chat. |
| `OPENAI_EMBEDDING_MODEL` | OpenAI model id | `text-embedding-3-small` | Overrideable; only `-small` and `-large` officially supported. |
| `OPENAI_EMBEDDING_DIMENSIONS` | int | `1536` | Advanced. Mismatching this with the schema's column type will fail at insert. |
| `EMBEDDING_SEARCH_THRESHOLD` | float | provider default (see 5.3) | Optional manual override of the cosine-distance cutoff. |

Startup validation in `lifespan` (or a small `validate_config()` called before the app accepts traffic):

- If `EMBEDDING_PROVIDER=openai` and `OPENAI_API_KEY` is missing → raise and abort.
- If `EMBEDDING_PROVIDER=local` and the `fastembed` import fails → raise (catch and report the offending dependency).
- Log the resolved provider, model, dimension, table, and threshold at INFO once.

### 5.5 Lazy model load (memory win)

This is the actual Railway memory benefit:

- Move `from fastembed import TextEmbedding` from module top of `services.py` to **inside** `LocalEmbeddingProvider.__init__`.
- Stop constructing `embedding_service` at module import (`services.py:70`). Construct exactly one provider via `get_provider()`, called lazily on first request or once in `lifespan` after the provider is chosen.
- Result: when `EMBEDDING_PROVIDER=openai`, neither `fastembed` nor `onnxruntime` is imported, the ~130 MB ONNX model is never read, and the warm-RSS savings are the difference we are looking for.
- `fastembed` and `onnxruntime` stay in `requirements.txt` (the same image must still serve local deployments). The cost is only image size, not memory, and is unchanged from today.

### 5.6 Re-embed / migration flow

The existing `/bookmarks/reembed` endpoint (`main.py:464`) already does the only operation that makes sense across providers: read `content_markdown`, chunk, embed, replace. We extend it:

1. Operator flips `EMBEDDING_PROVIDER` in Railway env and redeploys.
2. New container starts on the new provider. Search / ingest now read and write the **new** provider's table.
3. Old provider's table still contains stale data for every existing bookmark. Until each bookmark is re-embedded, it is **invisible to search**. New ingests work normally.
4. Each user triggers `/bookmarks/reembed` from the extension UI (already wired — `services.py:426`). Background job streams per bookmark, writes into the new provider's table.
5. Optionally: a one-shot admin script (extend `Search Backend/reembed.py`) iterates all users.

Document explicitly: switching providers does not delete old-provider data automatically. Operators can `TRUNCATE bookmark_embeddings` (or `_openai`) once the migration is verified, to reclaim disk.

### 5.7 Cost model

Order-of-magnitude check (`text-embedding-3-small` at $0.02 / 1M tokens):

- ~1000 bookmarks × ~3 k tokens average content = 3 M tokens for a full re-embed = **$0.06** one-time.
- Steady-state ingest of 30 new bookmarks/day × 3 k tokens = 90 k tokens/day ≈ 2.7 M tokens/month = **~$0.05/month**.
- Query embedding: 60 queries/day × ~20 tokens = 1.2 k tokens/day ≈ negligible.

Even at 10× these numbers we are below $1/month per user. Railway memory savings dwarf this.

## 6. Implementation plan

Phased so each step is independently shippable.

### Phase 1 — Abstraction without behaviour change

- Introduce `EmbeddingProvider` protocol and `LocalEmbeddingProvider` wrapping today's code.
- Replace direct uses of `embedding_service` with `get_provider()`.
- Keep model load eager for now to avoid mixing this with the lazy-load change.
- No new env vars yet; provider is hard-coded `local`.
- Tests: ingest + search behaviour unchanged.

### Phase 2 — OpenAI provider + new table

- Add `BookmarkEmbeddingOpenAI` model and `bookmark_embeddings_openai` table to `lifespan` bootstrap.
- Add `OpenAIEmbeddingProvider` with retry/backoff.
- Make ingest, search, and re-embed pick table + class from the active provider.
- Add `EMBEDDING_PROVIDER`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_EMBEDDING_DIMENSIONS` env vars + startup validation.
- Tests: end-to-end ingest → search round-trip with provider set to `openai` (mock OpenAI in CI, real key in a manual smoke).

### Phase 3 — Lazy local load

- Move `fastembed` import and `TextEmbedding(...)` construction inside `LocalEmbeddingProvider.__init__`.
- Remove module-level `embedding_service` singleton.
- Verify on Railway with `EMBEDDING_PROVIDER=openai` that idle RSS drops materially (use the `/proc/self/status` periodic logger from the memory roadmap).

### Phase 4 — Threshold tuning + docs

- Build a small offline eval (a few queries × known-relevant bookmarks) and tune `EMBEDDING_SEARCH_THRESHOLD` for OpenAI.
- Document the operator workflow for switching providers (env change → redeploy → re-embed per user).
- Update `Railway/DEPLOYMENT.md` with the new env vars.

## 7. Risks and open questions

- **Threshold tuning.** The cosine-distance threshold is a magic number tuned for BGE. The OpenAI default in 5.3 is a guess; ship behind a config knob and tune before recommending OpenAI as the default.
- **Vendor lock-in for hosted deployment.** A hard OpenAI dependency in hosted mode means an OpenAI outage takes search down. Mitigation: provider abstraction makes adding a fallback (e.g. Voyage, Cohere) cheap later.
- **Cost on abusive ingest.** A user pasting a 1 MB markdown blob hits OpenAI tokens quickly. Existing rate limit is 10 ingests/minute (`main.py:235`). Consider an additional per-request token cap or content-size cap before this matters.
- **Schema drift.** Adding a second embeddings table doubles the surface area of the bootstrap SQL. If a third provider is ever added, generate the SQL from `EmbeddingProvider` metadata rather than hand-writing.
- **Per-user provider selection.** Out of scope for v1 but cheap to add later: store `provider` on `Bookmark` and route per row. Worth revisiting only if multi-tenant deployments want to bill OpenAI tokens per user.
- **Re-embed coverage.** Today's `/bookmarks/reembed` is user-initiated. Across many users the operator has no easy "re-embed everything" button. A small admin CLI built on existing helpers closes the gap.
- **Dimension override.** `OPENAI_EMBEDDING_DIMENSIONS` is exposed but the schema is fixed at 1536. Calling it out as advanced is honest; locking it down (ignore env, always 1536) is also defensible for v1.

## 8. Acceptance criteria

- Setting `EMBEDDING_PROVIDER=local` (or leaving unset) produces byte-identical behaviour to today.
- Setting `EMBEDDING_PROVIDER=openai` with a valid key:
  - Skips `fastembed` import entirely (verified via `sys.modules` inspection in a test).
  - Ingests new bookmarks into `bookmark_embeddings_openai`.
  - Searches return relevant results above the configured threshold.
  - Idle container RSS on Railway drops measurably vs. the local provider (target: < 500 MB per the memory roadmap goal).
- `/bookmarks/reembed` correctly re-embeds an existing user's content into whichever provider is currently active.
- Startup fails loudly and early if the provider is misconfigured.
