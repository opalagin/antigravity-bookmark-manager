# Automatic Bookmark Tagging — Specification

Status: Draft
Author: brainstorm with Claude
Date: 2026-11-06

## 1. Goal

Generate a short, high-quality tag list for a bookmark **at ingest time**, based on the bookmark's content **and the user's existing tag vocabulary**. The user may still review and edit the proposed tags before the bookmark is saved. The design must:

1. Reuse existing tags whenever one of them fits. Avoid proliferation (no near-duplicate tags like `rest-api`, `rest_apis`, `REST APIs`).
2. Keep each tag short — 1–2 words, lowercase, kebab-case, slash-delimited for hierarchy per the PRD tag convention (`work/projects/auth`).
3. Be cheap enough to run on every save (sub-cent, sub-second).
4. Degrade gracefully with no network / no API key (fall back to empty tags; user tags manually).

## 2. Motivation

Today both extensions ship bookmarks with an **empty** tag array:
- `Chrome Plugin/popup.js:52-57` — `window.api.saveBookmark(url, title, content, [])` (comment literally says *"Removed tags"*).
- `Firefox Plugin/popup.js` — mirror of the same call.

The PRD ingestion flow (`Docs/prd.md:40-47`) specifies *"Suggests tags (optional AI pre-fetch). User confirms/edits tags."* — this step was dropped during an earlier UI simplification and never came back. As a result:

- All bookmarks arrive untagged. The Manager UI's tag-tree (`Docs/prd.md:134-138`) is empty for new users and never fills unless the user manually tags each bookmark.
- Hierarchical tag features (`work/projects/auth` grouping, tag-tree rename, bulk prefix rewrite) have nothing to operate on.
- Semantic search works, but **tag-based filtering** — the fast path for "show me all my React bookmarks" — is unusable.

Doing this manually is the right escape hatch for power users but a bad default: the user has already decided to save the page, and bouncing them into a tag-entry UI is friction. An automatic suggestion that is *usually right* and *always editable* is the shape of the fix.

## 3. Non-goals

- **Not** fully autonomous tagging without any user visibility. The suggested tags are always shown in the save flow and can be edited before commit. (A silent "if the request has `tags: []`, fill them in" path on the server is still provided — see §5.6 — for scripted ingests and future bulk imports, but the extension always goes through the suggest-first flow.)
- **Not** retro-tagging the existing corpus. A separate `/bookmarks/retag` admin endpoint is listed as a future item in §8; v1 only tags newly ingested bookmarks.
- **Not** building a learned tag taxonomy. Tags are still the user's own flat slash-path strings stored in `Bookmark.tags: TEXT[]`. We only *propose* which ones to use.
- **Not** language-specific tagging rules. The model handles non-English content naturally; we do not impose a required tag language.
- **Not** merging near-duplicate existing tags automatically (e.g. folding `react` and `reactjs` into one). That is a separate curation feature.
- **Not** adding a new ML runtime. Reuse the OpenAI client already wired for chat (`services.py:30-37`) and the embedding provider already wired for search (`services.py:60-222`). No new model files, no local training.

## 4. Current state (reference)

- `Search Backend/main.py:481-509` — `POST /bookmarks` accepts `payload.tags: list[str]` and stores it verbatim via `ingestion_service.process_bookmark`. No tag inference anywhere on the server path.
- `Search Backend/services.py:571-581` — `ManagementService.get_tags` returns `[{tag, count}]` for a user, scoped to their own bookmarks. This is the authoritative source for "what tags does this user already have".
- `Search Backend/services.py:30-37` — `_get_openai_client()` memoized `AsyncOpenAI`. Used today by `SearchService.chat` with model `gpt-4o-mini` (`services.py:491`). Reuse both.
- `Search Backend/services.py:414-476` — the chat path also supports an `OLLAMA_BASE_URL` / `OLLAMA_MODEL` fallback, selected via `LLM_PROVIDER`. The tagging path should mirror this so self-hosted deployments are covered.
- `Search Backend/models.py:15-32` — `Bookmark.tags: list[str]` via Postgres `ARRAY(VARCHAR)`. No normalization constraint. Tags are opaque strings; hierarchy is a `/`-delimited convention only.
- `Chrome Plugin/popup.js:17-100` / `Firefox Plugin/popup.js` — the save handler runs synchronously after content extraction. It does **not** currently round-trip to the backend before calling `saveBookmark`. The new flow (§5.4) adds one extra call in between.
- `Chrome Plugin/api.js`, `Firefox Plugin/api.js` — single `api` object with `_fetch`; new endpoints land here first.

## 5. Design

### 5.1 Approach: LLM with existing-tag grounding (recommended)

Three approaches were considered. The decision matrix drives the pick:

| | A. Pure LLM | B. Embedding-nearest-tag | C. Hybrid (B then A on miss) |
|---|---|---|---|
| Reuses existing tags | Prompt-controlled | Mechanically guaranteed | Guaranteed for hits |
| Proposes new tags | Yes | **No** (bootstrap-blind) | Yes |
| Handles synonyms (`react` vs `reactjs`) | Yes | Partial (depends on embedding) | Yes |
| Respects hierarchy (`work/projects/auth`) | Yes, via prompt | Accidental at best | Yes |
| Cost per save | ~$0.0003 | ~$0.00001 (one embed we already compute) | ~$0.0001 (most saves hit) |
| Latency per save | +300–700 ms | +10 ms | +10–700 ms |
| Complexity | Low | Medium (needs tag-embedding cache) | High |
| Zero-existing-tags user | Works | **Fails** (nothing to match) | Falls through to LLM |

**Picked: A, structured as an LLM call with the user's existing tag list passed as context.** Rationale:

- The user's explicit requirement ("keep tags short, don't proliferate") is a *policy* problem. Policies belong in the prompt, not in a vector-distance threshold.
- The cost difference between A and C (~$0.0002 per save) is below noise for a pilot; the complexity difference (one call vs. maintained tag-embedding cache + miss detection) is not.
- The embedding cache in B/C must be invalidated whenever the user renames or deletes tags — our existing bulk-rename code path (`services.py:624-655`) would need matching maintenance. More surface area, no user-visible win.
- C is listed in §8 as a future optimization gated on cost telemetry.

### 5.2 Flow overview

```
+-----------+                                        +---------+
| Extension | 1. Extract content (Readability)        | Backend |
|           | 2. POST /tags/suggest { url, title,     |         |
|           |                        content_markdown }|         |
|           | --------------------------------------> |         |
|           |                                         |  LLM    |
|           |                                         |  call   |
|           | 3. { tags: ["react", "web/frontend"] }  |         |
|           | <-------------------------------------- |         |
| 4. Show chips in popup, user edits/approves.        |         |
| 5. POST /bookmarks { ..., tags: <final list> }      |         |
|           | --------------------------------------> |         |
+-----------+                                         +---------+
```

Only step 2 is new on the server. Step 5 is unchanged — existing `POST /bookmarks` already stores whatever tags the client sends.

### 5.3 Endpoint

**`POST /tags/suggest`** — stateless. Does not create a bookmark, does not touch the embeddings table, does not write anywhere.

Request:
```json
{
  "url": "https://example.com/article",
  "title": "Introducing React Server Components",
  "content_markdown": "..."
}
```

Response:
```json
{
  "tags": ["react", "web/frontend"],
  "source": "llm",
  "reused_existing": ["react"],
  "new_tags": ["web/frontend"]
}
```

Fields:
- `tags` — the suggested list, already deduplicated, normalized (see §5.5), and clipped to `TAG_SUGGEST_MAX` (default 5).
- `source` — `"llm"`, `"ollama"`, or `"fallback"` (empty-tags path). Used for client telemetry / display only.
- `reused_existing`, `new_tags` — audit split. The extension UI can mark reused tags with a different chip style so the user sees at a glance which suggestions are from their existing vocabulary.

Status codes:
- `200` on success, **including every provider failure** (timeout, rate limit, refusal, malformed output). These return `tags: []`, `source: "fallback"` and a `fallback_reason` (§5.7). Suggestion failure is never an HTTP error.
- `401` via existing auth dep (`get_current_user`).
- `413` if the raw request body exceeds `TAG_SUGGEST_MAX_REQUEST_BYTES` (§5.3.1).
- `422` if a field exceeds its length bound (§5.3.1).
- `429` from the rate limiter (§5.3.2).

Auth: standard `get_current_user` dep.

#### 5.3.1 Input bounds

The backend has no body-size guard today, and SlowAPI only does rate limiting, so this must be added explicitly. Use two layers:

1. **Raw request bytes.** A small ASGI middleware (new, in `main.py`) rejects with `413` any request to `/tags/suggest` or `/bookmarks` whose `Content-Length` exceeds the limit. Requests without `Content-Length` (chunked) are counted while the body streams and aborted once over the limit. Limits: `TAG_SUGGEST_MAX_REQUEST_BYTES` (default 262144 = 256 KiB) for `/tags/suggest`. `/bookmarks` gets its own `INGEST_MAX_REQUEST_BYTES` (default 2 MiB) so large articles can still be saved. Measure bytes on the wire, before JSON decoding.
2. **Decoded field lengths.** Pydantic `Field(max_length=...)` on the request model, measured in characters after JSON decoding:
   - `url` ≤ 2048
   - `title` ≤ 512
   - `content_markdown` ≤ 200000 (it is truncated to `TAG_CONTENT_SNIPPET_CHARS` before the prompt anyway; this bound only rejects abuse)

   Violations return `422`.

**Prompt-side bounds** (applied in `TaggingService`, not rejected):
- Title and URL are truncated to 300 and 500 characters in the prompt.
- Vocabulary is capped at `TAG_VOCAB_MAX` tags (default 200), and any stored tag longer than 100 characters is skipped.
- The rendered vocabulary block is capped at `TAG_VOCAB_MAX_CHARS` (default 8000), dropping the least-used tags first.

Together these bound the prompt at roughly 4k input tokens whatever the input.

#### 5.3.2 Rate limiting

The existing `Limiter(key_func=get_remote_address)` (`main.py:218`) keys by IP. Copying the `/chat` pattern would make users behind one NAT share a quota. Add a user key function:

```python
def user_rate_key(request: Request) -> str:
    # Set by get_current_user; falls back to IP for unauthenticated hits.
    return getattr(request.state, "user_sub", None) or get_remote_address(request)
```

SlowAPI evaluates the key before FastAPI resolves dependencies, so `request.state` isn't populated yet. Instead, `user_rate_key` decodes the bearer JWT itself (signature and `exp` only, via the same `decode_token` helper in `auth.py`; one HMAC, no DB) and returns `user:<sub>`. If the token is missing or invalid, it returns `ip:<addr>`, and the request then fails auth with `401` anyway.

Apply it with `@limiter.limit("20/minute", key_func=user_rate_key)` on `/tags/suggest` only. Existing endpoints keep IP keys; moving them is out of scope.

### 5.4 Server-side algorithm

In a new `TaggingService` in `services.py` (or a dedicated `tagging.py`; same module boundary trade-off as `auth.py` in the JWT spec):

```python
class TaggingService:
    def __init__(self, management_service: ManagementService):
        self.management_service = management_service

    async def suggest_tags(
        self,
        session: AsyncSession,
        user_id: str,
        title: str,
        url: str,
        content_markdown: str,
    ) -> TagSuggestion: ...
```

Steps:

1. **Load the user's tag vocabulary.** Reuse `ManagementService.get_tags(session, user_id)` and discard anything with `count == 0` (defensive — the query already filters, but keeps the contract explicit). Sort by `count desc` so the model sees the most-used tags first. Clip to `TAG_VOCAB_MAX` (default 200). For a pilot user this is the full list; for heavy users it keeps the prompt bounded.
2. **Prepare the content snippet.** Prompt tokens are the dominant cost. Truncate `content_markdown` to `TAG_CONTENT_SNIPPET_CHARS` (default 6000 ≈ ~1500 tokens). Prepend the title and URL — titles and domains are usually more signal-dense than mid-article prose.
3. **Build the prompt** per §5.5.
4. **Call the LLM** per the configured provider (see §5.7).
5. **Normalize and validate** the raw model output per §5.6.
6. **Split returned tags** into `reused_existing` vs `new_tags` using exact-string match against the vocabulary (after normalization — see §5.6).
7. **Return** the `TagSuggestion`.

### 5.5 Prompt

System prompt (fixed, versioned in code as `TAG_SUGGEST_SYSTEM_PROMPT_V1`):

```
You suggest tags for a user's bookmark. You will see:
  - the bookmark's title, URL, and a snippet of its content, and
  - a list of tags the user has already used, sorted by frequency.

Return a JSON object matching the schema:
  { "tags": [string, ...] }

Rules, in order of priority:
1. If one of the user's existing tags fits the bookmark, reuse it verbatim.
   Do not invent a new tag that is a synonym, singular/plural variant, or
   casing variant of an existing one.
2. Suggest at most 5 tags. Fewer is better. One well-chosen tag beats five
   mediocre ones.
3. Each tag:
   - is lowercase where the script has case,
   - joins words with "-" (kebab-case) where the script uses spaces,
   - is 1 or 2 words only (not counting the "-" within a kebab-case word
     like "machine-learning"),
   - contains only letters (any language), digits, "-", and "/" (slashes
     denote hierarchy, e.g. "work/projects/auth"),
   - is written in the same language as the user's existing tags when
     an existing tag fits; otherwise in the content's language,
   - is specific enough to be useful but general enough to apply to more
     than one bookmark over time.
4. Use hierarchy ("parent/child") only when the parent already exists in
   the user's tag list or when there is an obvious grouping (e.g.
   "programming/rust"). Do not invent deep hierarchies for one bookmark.
5. Do not include the article's language, publication date, URL fragments,
   or author names as tags.
6. If the content is empty, non-informative, or clearly not an article
   (login page, 404, paywall), return { "tags": [] }.

Think carefully about rule 1. Proliferation of near-duplicate tags is the
worst outcome.
```

User prompt (template):

```
Existing tags (most used first):
<tag, tag, tag ...>   # or "(none yet)" when vocab is empty

Bookmark:
  Title: <title>
  URL: <url>
  Content snippet:
<content_snippet>
```

OpenAI call uses structured outputs:

```python
response = await client.beta.chat.completions.parse(
    model=os.getenv("TAGGING_LLM_MODEL", "gpt-4o-mini"),
    messages=[
        {"role": "system", "content": TAG_SUGGEST_SYSTEM_PROMPT_V1},
        {"role": "user", "content": user_prompt},
    ],
    response_format=TagSuggestionModel,  # Pydantic: tags: list[str]
    temperature=0.0,
)
```

Temperature `0.0` is deliberate — tagging is a deterministic classification task; creativity is a bug here.

### 5.6 Normalization and validation

**Tag language policy:** tags may be in any script. Validation is Unicode-aware. Accented Latin, Cyrillic, CJK and other letters are valid tag characters. The prompt's "lowercase kebab-case" rule applies only to scripts that have case and word separators. The normalizer never deletes letters.

The normalizer is used for **two different purposes**, which must not be confused:

- **Canonical key** — `tag_key(s)` is used **only for matching**. It is never stored.
- **Output string** — the value actually returned and stored.

`tag_key(s)`:
1. Unicode NFKC normalization.
2. `casefold()` (not `lower()`: handles `ß`, Turkish dotted I, and similar cases).
3. Trim. Replace runs of whitespace or `_` with `-`.
4. Collapse consecutive `-` or `/`. Trim leading and trailing `-` and `/` from each segment and from the whole string.

Cleaning a model-proposed tag into its output form: apply `tag_key` steps 1, 3 and 4, then `str.lower()` (a no-op for caseless scripts; `lower` rather than `casefold`, so `straße` is kept as written). Then validate:
1. Allowed characters: Unicode letters (`\p{L}`), combining marks (`\p{M}`), digits (`\p{Nd}`), `-`, `/`. Use the `regex` package, since stdlib `re` lacks `\p{}`. Any other character → **reject the whole tag** (don't silently strip it; a stripped tag is a different tag).
2. Reject if the segment count exceeds `TAG_MAX_DEPTH` (default 4), or any segment exceeds `TAG_SEGMENT_MAX_LEN` (default 40 code points).

**Mapping to existing vocabulary (prevents duplicates):**
- Build `key → stored string` from the user's vocabulary.
- For each suggestion, if `tag_key(suggestion)` matches a key, **return the stored string exactly as stored** (e.g. the user's `React`, not `react`) and count it in `reused_existing`.
- **Collision rule:** if several stored tags share a key (e.g. the user already has both `React` and `react`), return the one with the highest bookmark count. On a tie, return the lexicographically smallest. Never merge them; that is the curation feature excluded in §3.
- Otherwise the cleaned suggestion is a new tag, listed in `new_tags`.

Then deduplicate by key within the response and clip to `TAG_SUGGEST_MAX` (default 5).

**Existing tags are never rewritten.** The normalizer is applied only to model output. Stored tags and tags typed by the user pass through `POST /bookmarks` unchanged, as they do today.

If validation removes all tags, the response is `{"tags": [], "source": "fallback", "fallback_reason": "invalid_output"}`.

### 5.7 Provider selection

Mirror the existing `LLM_PROVIDER` switch in `SearchService.chat` (`services.py:414`):

- `TAGGING_LLM_PROVIDER` defaults to the value of `LLM_PROVIDER` (default `openai`). An explicit override lets operators route chat to OpenAI and tagging to Ollama, or vice versa, without a code change.
- OpenAI path: structured outputs via `client.beta.chat.completions.parse` as shown above.
- Ollama path: POST to `{OLLAMA_BASE_URL}/api/chat` with `format: "json"`. Parse the JSON body, then run it through the normalization pipeline (§5.6) exactly as the OpenAI output. Ollama models under-respect schemas; the normalizer is the last line of defense.
- No-provider path: if `_get_openai_client()` returns `None` and `TAGGING_LLM_PROVIDER` is not `ollama`, return `{"tags": [], "source": "fallback", "fallback_reason": "disabled"}`. No error. Matches the chat fallback behavior.

#### 5.7.1 Deadlines, retries and failure handling

The extension's 4-second timeout doesn't stop backend inference, so the server enforces its own deadline:

- **Overall deadline:** `TAG_SUGGEST_DEADLINE_SECONDS` (default 3.5; slightly under the client timeout). The whole `suggest_tags` call, including the vocabulary query and all provider attempts, runs inside `asyncio.timeout(deadline)`. On expiry the in-flight provider call is cancelled. Pass the remaining time into the HTTP client: OpenAI `timeout=`, httpx `timeout=` for Ollama. This ensures the socket is closed and not just abandoned.
- **Retries:** at most **1** retry, only for `APIConnectionError`, `APITimeoutError` and HTTP 5xx, and only if at least 1 s of deadline remains. **No retry** on `RateLimitError` (429): back off immediately to fallback. Retrying inside a 3.5 s budget only increases pressure. Construct the OpenAI client for this path with `max_retries=0` so the SDK's built-in retries don't silently exceed the budget.
- **Ollama:** use a single attempt with a deadline of `TAG_SUGGEST_OLLAMA_DEADLINE_SECONDS` (default 10, since local models are slower). The extension must wait longer than the server deadline. Add an unauthenticated `GET /config` returning `{ "tag_suggest_timeout_ms": <server deadline + 500> }`. The extension reads it once per popup open, defaulting to 4000 if the call fails.

Every failure maps to `200 {tags: [], source: "fallback", fallback_reason}`:

| Condition | `fallback_reason` |
|---|---|
| Deadline exceeded | `timeout` |
| Connection error / 5xx after retry | `provider_unavailable` |
| 429 from provider | `provider_rate_limited` |
| Structured-output refusal (`message.refusal` set) or content filter | `refused` |
| Parse failure, schema mismatch, or every tag rejected by §5.6 | `invalid_output` |
| Provider disabled or no key | `disabled` |
| Any other exception (logged with traceback) | `internal_error` |

Each reason is logged in the §5.10 telemetry line.

**Ingestion is never blocked by tagging.** For `auto_tag` (§5.9), the same `suggest_tags` is called with the same deadline. Any fallback results in the bookmark being stored with `tags: []`. Ingest's own success or failure is unaffected. The ingest response gains `auto_tag_status: "applied" | "fallback:<reason>" | "skipped"` so scripts can detect it.

### 5.8 Extension changes

Both extensions get the same logic; one description.

**`api.js`** gains:
```js
async suggestTags(url, title, contentMarkdown) {
    return this._fetch('/tags/suggest', {
        method: 'POST',
        body: JSON.stringify({ url, title, content_markdown: contentMarkdown }),
    });
}
```

**`popup.js`** save lifecycle (`Chrome Plugin/popup.js:17-100` and the `Firefox Plugin/popup.js` mirror). Today extraction runs inside the Save click handler. **Decision: preparation starts when the popup opens**, not on an extra "Prepare" click, so the common path stays a single Save click.

Explicit state machine:

```
idle ──popup open──▶ extracting ──ok──▶ suggesting ──resp/timeout──▶ ready
          │                │                    │
          │             error ─▶ extract_failed (Save disabled, "Retry" button)
          │                                     │
          │      (Save is ENABLED in both suggesting and ready)
          ▼                                     ▼
                         Save click ──▶ submitting ──▶ saved | save_failed
```

Rules:
1. **On popup open** (and only if the user is logged in and the tab is `http(s)`), inject and run `extract.js`, store `{url, title, content}` in popup memory, then call `suggestTags`. The chips input is shown immediately in an empty state with a "Suggesting…" hint.
2. **Save becomes available as soon as extraction succeeds** (state `suggesting`). The user doesn't wait for suggestions. If they click Save before the suggestion returns, the current chips (possibly empty) are submitted.
3. **User edits always win.** Each chip records its origin: `suggested` or `user`. When a suggestion response arrives:
   - If the user has made **no edits** since the request was issued, replace the suggested chips.
   - If the user **has edited** (added, removed, or typed into the input), merge: add only suggested tags not already present (by `tag_key`) and not previously removed by the user. Never remove a chip the user added or kept, and never re-add one the user removed.
4. **Stale responses are discarded.** Every `suggestTags` call (initial or Regenerate) gets an incrementing `requestId`. A response whose `requestId` isn't the latest is ignored.
5. **Submission freezes tags.** On Save click, the state moves to `submitting`. The tag list is snapshotted, the chip editor and Regenerate become read-only, and any in-flight suggestion is aborted via `AbortController`. Responses arriving after this point are dropped.
6. **Regenerate** is only allowed in `suggesting`/`ready`. It applies rule 3 (doesn't clobber user edits) and has a 5-second client-side throttle.
7. **Popup closed mid-flight:** nothing is saved; the in-flight request simply dies with the popup. Saving only happens on an explicit Save click.

The `suggestTags` timeout is the `tag_suggest_timeout_ms` value from `GET /config` (§5.7.1), defaulting to 4 s. On timeout or error, the hint changes to "No suggestions; add tags manually" and the state goes to `ready`.

The chip UI:
- Suggested-reused tags use the primary-color pill style.
- Suggested-new tags use a lighter dashed-border pill style — hints "this is new; are you sure?".
- Each chip has an `×` to remove. A text input at the end accepts free-typed new tags (comma or Enter commits a chip). Typing also autocompletes from `GET /tags` (already exists) via the Manager UI's existing autocomplete helper — share the function.
- A small "Regenerate" button next to the chips re-calls `/tags/suggest` (rate-limited at 20/min server-side; add a 5-second client-side throttle to be safe).

**Manifest permissions / content security:** no new permissions. All calls go through the existing authed `api._fetch`.

**No new UI surface for tag editing beyond save.** The Manager UI already supports post-hoc tag editing (`Docs/prd.md:139-152`). Suggested tags are editable only at ingest time.

### 5.9 "Auto-fill on empty" server fallback (scripted ingests)

For callers that cannot run the two-step flow — admin scripts, future bulk importers, a hypothetical mobile share-sheet — add a flag to `POST /bookmarks`:

```json
{ "url": "...", "title": "...", "content_markdown": "...", "tags": [], "auto_tag": true }
```

If `auto_tag` is `true` **and** `tags` is empty on the request, the ingest handler calls `TaggingService.suggest_tags` internally before `IngestionService.process_bookmark`, and the stored bookmark carries the suggested tags as if the client sent them. If `tags` is non-empty, `auto_tag` is ignored.

Rationale for this being a flag, not default behavior: the extension flow deliberately gives the user a chance to edit. Making it default on an empty `tags` array would surprise clients that intentionally store untagged bookmarks (e.g. a "read later" import).

### 5.10 Telemetry

Log one INFO line per suggest call:

```
tags.suggest user_sub=<sub> source=<llm|ollama|fallback>
  fallback_reason=<reason|-> attempts=<n>
  vocab_size=<n> content_chars=<n> returned=<n>
  reused=<n> new=<n> latency_ms=<n>
```

No content, no tags, no URLs in logs — only counts. Enough to answer *"are suggestions actually reusing the user's existing vocabulary, or always inventing new tags?"*, which is the one metric that tells us the prompt is working.

## 6. Configuration

New env vars:

| Var | Default | Notes |
|---|---|---|
| `TAGGING_LLM_PROVIDER` | value of `LLM_PROVIDER`, else `openai` | `openai` \| `ollama` \| `off` (last disables suggestions entirely). |
| `TAGGING_LLM_MODEL` | `gpt-4o-mini` | For OpenAI only. |
| `TAGGING_OLLAMA_MODEL` | value of `OLLAMA_MODEL` | For Ollama only. |
| `TAG_SUGGEST_MAX` | `5` | Hard cap on returned tags. |
| `TAG_VOCAB_MAX` | `200` | Existing tags passed to the prompt (most-used first). |
| `TAG_CONTENT_SNIPPET_CHARS` | `6000` | Content truncation before the prompt. |
| `TAG_MAX_DEPTH` | `4` | Max slash-segments per tag. |
| `TAG_SEGMENT_MAX_LEN` | `40` | Max chars per slash-segment. |
| `TAG_SUGGEST_MAX_REQUEST_BYTES` | `262144` | Raw body limit for `/tags/suggest` (§5.3.1). |
| `INGEST_MAX_REQUEST_BYTES` | `2097152` | Raw body limit for `/bookmarks`. |
| `TAG_VOCAB_MAX_CHARS` | `8000` | Cap on the rendered vocabulary block in the prompt. |
| `TAG_SUGGEST_DEADLINE_SECONDS` | `3.5` | Server-side overall deadline (OpenAI). |
| `TAG_SUGGEST_OLLAMA_DEADLINE_SECONDS` | `10` | Server-side deadline (Ollama). |

All validated once at startup (same pattern as `EMBEDDING_PROVIDER` in `services.py:161-222`): unknown `TAGGING_LLM_PROVIDER` → startup error; `openai` + missing `OPENAI_API_KEY` → warn and silently downgrade to `off` (matches chat behavior, which also just no-ops on missing key).

## 7. Risks and open questions

- **Prompt stability over time.** `gpt-4o-mini` behavior can drift. The system prompt is versioned (`TAG_SUGGEST_SYSTEM_PROMPT_V1`) so a prompt change ships atomically with its version bump and can be rolled back. No stronger guarantee until we have an eval set.
- **No offline eval set.** Prompt rules 1 and 4 (reuse, hierarchy) are the hardest to verify by inspection. Build a tiny golden set — 20 real bookmarks per user, each with an expected tag list — and check the model against it before enabling the flow for a new provider / model. Deferred past v1 but called out as the first follow-up.
- **Cost**: ~$0.0003 per save at gpt-4o-mini quoted pricing (title + URL + 1.5 k content tokens + ~50 output tokens, prompt mostly cacheable across saves within a user). Negligible for a pilot. Would matter at 100× scale; the hybrid in §8 is the lever.
- **Latency**: budgeted at 300–700 ms for OpenAI, 1–3 s for small Ollama models. The extension never blocks saving on this — the suggestion call runs while the user still has the popup open; if it is late, the user types tags manually or saves without them.
- **Tag explosion by content type.** News articles about one-off events (names, places, dates) risk producing tags that will never appear again (`sam-altman`, `openai-dev-day-2026`). Prompt rule 5 and the 1–2 word constraint push back on this, but the rate of singleton tags per user is a metric worth watching — expose it on `/tags` later as a diagnostic.
- **Multi-language users.** The prompt prefers an existing tag's language when one fits. Otherwise tags follow the content's language, so a bilingual user may get two parallel vocabularies (`programming` and `programmierung`). Validation keeps both intact (§5.6). Cross-language merging is part of the deferred curation feature.
- **New dependency.** The `regex` package is needed for `\p{L}`-style classes. It is small and pure-wheel; add it to `Search Backend` dependencies via uv.
- **"Regenerate" button abuse.** Rate-limited server-side; the only remaining concern is cost drift from power users spamming regenerations. Watch telemetry; if it matters, add a per-save-session cap client-side.
- **Server-side auto-tag flag and consent.** `auto_tag: true` with an empty `tags` list is a convenience for scripted ingests. It is an opt-in flag, not a default, precisely so the extension's confirm-before-save contract stays unambiguous.

## 8. Implementation phases

Each phase is independently shippable and testable.

**Phase 1 — Backend: `TaggingService` + `/tags/suggest` endpoint.**
- Add `TaggingService` with the §5.4 algorithm, OpenAI path only.
- Add the normalizer (§5.6) as a pure function with unit tests — this is the piece most likely to regress silently.
- Add `POST /tags/suggest` in `main.py`, authed, rate-limited.
- Add the deadline, retry and fallback handling (§5.7.1), the body-size middleware and field bounds (§5.3.1), and the user-keyed rate limit (§5.3.2).
- No extension changes yet. Verify end-to-end with `curl` + a seeded test user.

Acceptance checks (automated, mocked provider):
- Normalizer and mapping:
  - Vocabulary `["React"]` + model returns `react` → response `["React"]`, `reused_existing=["React"]`, `new_tags=[]`.
  - Vocabulary `["React" (3), "react" (5)]` + model `REACT` → `["react"]` (higher count). On a tie, the lexicographically smallest wins.
  - Model returns `Café`, `機械学習`, `программирование/rust` → all kept as `café`, `機械学習`, `программирование/rust`.
  - Model returns `c++` → rejected (not stripped to `c`).
  - Vocabulary `["Straße"]` + model `strasse` → `["Straße"]`.
  - Stored tags are byte-identical before and after any suggest or ingest call.
- Provider failures: each row in the §5.7.1 table returns `200`, `tags: []` and the right `fallback_reason`. A mocked provider that sleeps 10 s makes the endpoint return within `deadline + 0.2 s`, and the mock observes cancellation. A 429 makes exactly one provider attempt. A connection error makes at most two.
- Input bounds: a 300 KiB body → `413`, both with `Content-Length` and chunked without it. `title` of 513 chars → `422`. A vocabulary of 5000 long tags → rendered prompt ≤ `TAG_VOCAB_MAX_CHARS`.
- Rate limit: two users from the same IP each get 20 requests/min independently. The 21st request from one user → `429` while the other still gets `200`.

**Phase 2 — Backend: Ollama path and configuration knobs.**
- Mirror the Ollama JSON-mode branch from `SearchService.chat`.
- Add all env vars in §6 and validate at startup, plus `GET /config`.
- Hook `TAGGING_LLM_PROVIDER=off` to short-circuit with `source: "fallback"`, `fallback_reason: "disabled"`.

Acceptance checks:
- Ollama returning non-JSON or a schema-violating JSON → `invalid_output`.
- Ollama unreachable → `provider_unavailable` within the Ollama deadline.
- `GET /config` reflects the active deadline.
- Unknown provider value → startup fails.

**Phase 3 — Extension UI: suggest-first save flow.**
- Chrome: `api.suggestTags`, `GET /config` read, chip UI, the §5.8 state machine, autocomplete shared with the Manager.
- Firefox: identical.
- Bump both `manifest.json` versions.

Acceptance checks (manual script in `Chrome Plugin/INSTRUCTIONS.md`, plus unit tests of the chip-merge function if feasible):
- Save is enabled before the suggestion returns. Clicking it submits the current (possibly empty) chips.
- Delay the server 3 s, add a chip by hand, let the suggestion arrive → the hand-added chip is kept and suggestions merge in.
- Remove a suggested chip, then Regenerate → the removed tag isn't re-added.
- Click Regenerate twice quickly while delaying the first response → only the latest response is applied.
- Click Save while a suggestion is in flight → the saved bookmark's tags equal the snapshot at click time. The late response doesn't change the UI or trigger a second save.
- Backend down → the popup shows "No suggestions" and saving still succeeds.
- Extraction fails (e.g. a `chrome://` page) → Save disabled and the Retry button is shown.

**Phase 4 — Server-side `auto_tag` flag.**
- Extend the `BookmarkIngestRequest` schema with `auto_tag: bool = False`.
- Wire the ingest handler to call `TaggingService.suggest_tags` when the flag is set and `tags` is empty.
- Add `auto_tag_status` to the ingest response.
- No extension change (the flag is for scripted ingests; the extension sends explicit tags).

Acceptance checks:
- With the provider mocked to time out, `POST /bookmarks` with `auto_tag: true` still returns success within `deadline + ingest time`, stores `tags: []`, and reports `auto_tag_status: "fallback:timeout"`.
- With non-empty `tags`, the provider is never called (`auto_tag_status: "skipped"`).

**Phase 5 — Follow-ups (not in v1, listed for completeness).**
- `POST /bookmarks/retag` — re-suggest tags for all of a user's existing bookmarks (background job pattern from `ManagementService.reembed_user_bookmarks` is the template).
- Hybrid approach C from §5.1: cached per-user tag embeddings, LLM only on low-similarity misses. Gate on cost telemetry from Phases 1–3.
- Golden eval set + CI check that prompts don't regress on it.
- "Similar-tag" curation UI in the Manager: surface near-duplicate tags across the user's vocabulary and offer a merge action.

Phases 1–2 are backend-only. Phase 3 is UI-only. Phase 4 is a trivial extension of Phase 1. The three phases needed to deliver the user-visible feature are 1, 2, and 3.
