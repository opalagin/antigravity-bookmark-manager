import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import time
import traceback
import unicodedata
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx
import regex
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession


@asynccontextmanager
async def _async_timeout(delay: Optional[float]) -> AsyncIterator[None]:
    if delay is None:
        yield
        return
    builtin_timeout = getattr(asyncio, "timeout", None)
    if builtin_timeout is not None:
        async with builtin_timeout(delay):
            yield
        return
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    timed_out = False

    def _cancel() -> None:
        nonlocal timed_out
        timed_out = True
        if task is not None:
            task.cancel()

    handle = loop.call_later(max(0.0, delay), _cancel)
    try:
        yield
    except asyncio.CancelledError:
        if timed_out:
            raise asyncio.TimeoutError()
        raise
    finally:
        handle.cancel()

logger = logging.getLogger("tags.suggest")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


TAG_SUGGEST_SYSTEM_PROMPT_V1 = """You suggest tags for a user's bookmark. You will see:
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
worst outcome."""


class TagSuggestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str]

    @field_validator("tags", mode="before")
    @classmethod
    def _ensure_string_list(cls, v: Any) -> Any:
        if not isinstance(v, list):
            raise ValueError("tags must be a list")
        for item in v:
            if not isinstance(item, str):
                raise ValueError("each tag must be a string")
        return v


@dataclass
class TagSuggestion:
    tags: list[str] = field(default_factory=list)
    source: str = "fallback"  # "llm" | "ollama" | "fallback"
    reused_existing: list[str] = field(default_factory=list)
    new_tags: list[str] = field(default_factory=list)
    fallback_reason: Optional[str] = None


class _ProviderFallbackError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --- Configuration helpers (§6) ---


def _parse_int_env(name: str, default: int, min_val: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"Invalid {name} value: '{raw}'. Must be an integer.")
    if val < min_val:
        raise ValueError(f"Invalid {name} value: {val}. Must be >= {min_val}.")
    return val


def _parse_float_env(name: str, default: float, min_val: float = 0.01) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        val = float(raw)
    except ValueError:
        raise ValueError(f"Invalid {name} value: '{raw}'. Must be a float.")
    if val < min_val:
        raise ValueError(f"Invalid {name} value: {val}. Must be >= {min_val}.")
    return val


def get_configured_tagging_provider(validate_only: bool = False) -> str:
    raw = os.getenv("TAGGING_LLM_PROVIDER")
    if not raw:
        raw = os.getenv("LLM_PROVIDER", "openai")
    provider = raw.strip().lower()
    if provider not in ("openai", "ollama", "off"):
        raise ValueError(
            f"Unknown TAGGING_LLM_PROVIDER: '{raw}'. "
            "Must be 'openai', 'ollama', or 'off'."
        )
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        if validate_only:
            logger.warning(
                "TAGGING_LLM_PROVIDER is 'openai' but OPENAI_API_KEY is missing; "
                "downgrading tagging provider to 'off'."
            )
        return "off"
    return provider


def get_tagging_llm_model() -> str:
    return os.getenv("TAGGING_LLM_MODEL", "gpt-4o-mini")


def get_tagging_ollama_model() -> str:
    return os.getenv(
        "TAGGING_OLLAMA_MODEL",
        os.getenv("OLLAMA_MODEL", "mistral:7b-instruct-q4_K_M"),
    )


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


def get_tag_suggest_max() -> int:
    return _parse_int_env("TAG_SUGGEST_MAX", 5)


def get_tag_vocab_max() -> int:
    return _parse_int_env("TAG_VOCAB_MAX", 200)


def get_tag_content_snippet_chars() -> int:
    return _parse_int_env("TAG_CONTENT_SNIPPET_CHARS", 6000)


def get_tag_max_depth() -> int:
    return _parse_int_env("TAG_MAX_DEPTH", 4)


def get_tag_segment_max_len() -> int:
    return _parse_int_env("TAG_SEGMENT_MAX_LEN", 40)


def get_tag_suggest_max_request_bytes() -> int:
    return _parse_int_env("TAG_SUGGEST_MAX_REQUEST_BYTES", 262144)


def get_ingest_max_request_bytes() -> int:
    return _parse_int_env("INGEST_MAX_REQUEST_BYTES", 2097152)


def get_tag_vocab_max_chars() -> int:
    return _parse_int_env("TAG_VOCAB_MAX_CHARS", 8000)


def get_tag_suggest_deadline_seconds() -> float:
    return _parse_float_env("TAG_SUGGEST_DEADLINE_SECONDS", 3.5)


def get_tag_suggest_ollama_deadline_seconds() -> float:
    return _parse_float_env("TAG_SUGGEST_OLLAMA_DEADLINE_SECONDS", 10.0)


def get_active_deadline_seconds() -> float:
    raw = os.getenv("TAGGING_LLM_PROVIDER") or os.getenv("LLM_PROVIDER", "openai")
    if raw.strip().lower() == "ollama":
        return get_tag_suggest_ollama_deadline_seconds()
    return get_tag_suggest_deadline_seconds()


def get_tag_suggest_timeout_ms() -> int:
    deadline = get_active_deadline_seconds()
    return int(round(deadline * 1000)) + 500


def validate_tagging_config() -> dict[str, Any]:
    """
    Validates all tagging configuration environment variables at startup.
    Raises ValueError on invalid provider or numeric bounds.
    """
    provider = get_configured_tagging_provider(validate_only=True)
    return {
        "provider": provider,
        "openai_model": get_tagging_llm_model(),
        "ollama_model": get_tagging_ollama_model(),
        "suggest_max": get_tag_suggest_max(),
        "vocab_max": get_tag_vocab_max(),
        "content_snippet_chars": get_tag_content_snippet_chars(),
        "max_depth": get_tag_max_depth(),
        "segment_max_len": get_tag_segment_max_len(),
        "suggest_max_request_bytes": get_tag_suggest_max_request_bytes(),
        "ingest_max_request_bytes": get_ingest_max_request_bytes(),
        "vocab_max_chars": get_tag_vocab_max_chars(),
        "deadline_seconds": get_tag_suggest_deadline_seconds(),
        "ollama_deadline_seconds": get_tag_suggest_ollama_deadline_seconds(),
    }


# --- Normalization and validation (§5.6) ---

_WS_OR_UNDERSCORE_RE = regex.compile(r"[\s_]+")
_MULTI_SLASH_RE = regex.compile(r"/+")
_MULTI_DASH_RE = regex.compile(r"-+")
_ALLOWED_TAG_CHARS_RE = regex.compile(r"^[\p{L}\p{M}\p{Nd}\-/]+$")


def _normalize_structure(s: str) -> str:
    """
    Applies tag_key steps 1, 3, and 4:
    1. Unicode NFKC normalization.
    3. Trim. Replace runs of whitespace or '_' with '-'.
    4. Collapse consecutive '-' or '/'. Trim leading and trailing '-' and '/'
       from each segment and from the whole string.
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.strip()
    s = _WS_OR_UNDERSCORE_RE.sub("-", s)
    s = s.strip("-/")
    if not s:
        return ""
    raw_segments = _MULTI_SLASH_RE.split(s)
    segments: list[str] = []
    for seg in raw_segments:
        cleaned_seg = _MULTI_DASH_RE.sub("-", seg).strip("-")
        if cleaned_seg:
            segments.append(cleaned_seg)
    return "/".join(segments)


def tag_key(s: str) -> str:
    """
    Canonical key used only for matching against existing tags and deduplication.
    Never stored.
    """
    if not isinstance(s, str):
        return ""
    s_nfkc = unicodedata.normalize("NFKC", s)
    s_folded = s_nfkc.casefold()
    return _normalize_structure(s_folded)


def clean_proposed_tag(
    s: str,
    max_depth: Optional[int] = None,
    segment_max_len: Optional[int] = None,
) -> Optional[str]:
    """
    Cleans a model-proposed tag into its output form (steps 1, 3, 4 + lower())
    and validates allowed characters and segment constraints.
    Returns None if the tag is invalid and must be rejected.
    """
    if not isinstance(s, str):
        return None
    if max_depth is None:
        max_depth = get_tag_max_depth()
    if segment_max_len is None:
        segment_max_len = get_tag_segment_max_len()

    cleaned = _normalize_structure(s).lower()
    if not cleaned:
        return None

    if not _ALLOWED_TAG_CHARS_RE.match(cleaned):
        return None

    segments = cleaned.split("/")
    if len(segments) > max_depth:
        return None
    for seg in segments:
        if not seg or len(seg) > segment_max_len:
            return None

    return cleaned


def build_vocab_map(vocab: list[dict[str, Any]]) -> dict[str, str]:
    """
    Builds key -> stored_tag mapping from the user's vocabulary.
    Collision rule (§5.6): highest bookmark count wins; on a tie,
    lexicographically smallest stored tag wins.
    """
    valid_items = [
        item
        for item in vocab
        if isinstance(item.get("tag"), str)
        and item["tag"]
        and int(item.get("count", 0)) > 0
    ]
    valid_items.sort(key=lambda item: (-int(item["count"]), item["tag"]))

    mapping: dict[str, str] = {}
    for item in valid_items:
        stored_tag: str = item["tag"]
        k = tag_key(stored_tag)
        if k and k not in mapping:
            mapping[k] = stored_tag
    return mapping


def normalize_and_map_tags(
    raw_tags: list[str],
    vocab: list[dict[str, Any]],
    suggest_max: Optional[int] = None,
    max_depth: Optional[int] = None,
    segment_max_len: Optional[int] = None,
) -> tuple[list[str], list[str], list[str], bool]:
    """
    Normalizes, validates, deduplicates, and maps model-proposed tags against
    the user's existing vocabulary.

    Returns (tags, reused_existing, new_tags, all_rejected).
    all_rejected is True when raw_tags was non-empty but every tag failed validation.
    """
    if suggest_max is None:
        suggest_max = get_tag_suggest_max()
    if max_depth is None:
        max_depth = get_tag_max_depth()
    if segment_max_len is None:
        segment_max_len = get_tag_segment_max_len()

    vocab_map = build_vocab_map(vocab)

    tags: list[str] = []
    reused_existing: list[str] = []
    new_tags: list[str] = []
    seen_keys: set[str] = set()
    valid_count = 0

    for raw in raw_tags:
        cleaned = clean_proposed_tag(
            raw, max_depth=max_depth, segment_max_len=segment_max_len
        )
        if cleaned is None:
            continue
        k = tag_key(cleaned)
        if not k:
            continue
        valid_count += 1
        if k in seen_keys:
            continue
        seen_keys.add(k)

        if k in vocab_map:
            stored = vocab_map[k]
            tags.append(stored)
            reused_existing.append(stored)
        else:
            tags.append(cleaned)
            new_tags.append(cleaned)

        if len(tags) >= suggest_max:
            break

    all_rejected = len(raw_tags) > 0 and valid_count == 0
    return tags, reused_existing, new_tags, all_rejected


def render_vocabulary_block(
    vocab: list[dict[str, Any]],
    vocab_max: Optional[int] = None,
    vocab_max_chars: Optional[int] = None,
) -> tuple[str, int]:
    """
    Prepares the sorted, clipped vocabulary block for the LLM prompt (§5.3.1, §5.4).
    - Skips tags with count <= 0 or length > 100 chars.
    - Sorts by (-count, tag).
    - Clips to TAG_VOCAB_MAX tags.
    - Caps rendered string at TAG_VOCAB_MAX_CHARS, dropping least-used tags first.
    Returns (rendered_block, included_vocab_count).
    """
    if vocab_max is None:
        vocab_max = get_tag_vocab_max()
    if vocab_max_chars is None:
        vocab_max_chars = get_tag_vocab_max_chars()

    filtered = [
        item
        for item in vocab
        if isinstance(item.get("tag"), str)
        and 0 < len(item["tag"]) <= 100
        and int(item.get("count", 0)) > 0
    ]
    filtered.sort(key=lambda item: (-int(item["count"]), item["tag"]))
    clipped = filtered[:vocab_max]

    kept_tags: list[str] = []
    current_len = 0
    for item in clipped:
        t = item["tag"]
        sep_len = 2 if kept_tags else 0
        if current_len + sep_len + len(t) > vocab_max_chars:
            break
        kept_tags.append(t)
        current_len += sep_len + len(t)

    if not kept_tags:
        return "(none yet)", 0
    return ", ".join(kept_tags), len(kept_tags)


def build_user_prompt(
    title: str,
    url: str,
    content_markdown: str,
    vocab_block: str,
    content_snippet_chars: Optional[int] = None,
) -> str:
    if content_snippet_chars is None:
        content_snippet_chars = get_tag_content_snippet_chars()
    title_bounded = (title or "")[:300]
    url_bounded = (url or "")[:500]
    content_bounded = (content_markdown or "")[:content_snippet_chars]

    return (
        "Existing tags (most used first):\n"
        f"{vocab_block}\n\n"
        "Bookmark:\n"
        f"  Title: {title_bounded}\n"
        f"  URL: {url_bounded}\n"
        "  Content snippet:\n"
        f"{content_bounded}"
    )


# --- OpenAI client for tagging (max_retries=0 per §5.7.1) ---

_tagging_openai_client: Optional[AsyncOpenAI] = None
_tagging_openai_key: Optional[str] = None


def _get_tagging_openai_client() -> Optional[AsyncOpenAI]:
    global _tagging_openai_client, _tagging_openai_key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    if _tagging_openai_client is None or _tagging_openai_key != api_key:
        _tagging_openai_client = AsyncOpenAI(api_key=api_key, max_retries=0)
        _tagging_openai_key = api_key
    return _tagging_openai_client


# --- TaggingService (§5.4, §5.7, §5.10) ---


class TaggingService:
    def __init__(self, management_service: Any):
        self.management_service = management_service

    async def _call_openai_once(
        self,
        client: AsyncOpenAI,
        model: str,
        user_prompt: str,
        timeout: float,
    ) -> list[str]:
        try:
            response = await client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": TAG_SUGGEST_SYSTEM_PROMPT_V1},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=TagSuggestionModel,
                temperature=0.0,
                timeout=timeout,
            )
        except ContentFilterFinishReasonError:
            raise _ProviderFallbackError("refused")
        except (LengthFinishReasonError, ValidationError, json.JSONDecodeError):
            raise _ProviderFallbackError("invalid_output")

        if not getattr(response, "choices", None):
            raise _ProviderFallbackError("invalid_output")

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        message = getattr(choice, "message", None)
        if message is None:
            raise _ProviderFallbackError("invalid_output")

        if finish_reason == "content_filter" or getattr(message, "refusal", None):
            raise _ProviderFallbackError("refused")
        if finish_reason == "length":
            raise _ProviderFallbackError("invalid_output")

        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, TagSuggestionModel):
                return parsed.tags
            if hasattr(parsed, "tags") and isinstance(parsed.tags, list):
                validated = TagSuggestionModel(tags=parsed.tags)
                return validated.tags
            raise _ProviderFallbackError("invalid_output")

        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            try:
                validated = TagSuggestionModel.model_validate_json(content)
                return validated.tags
            except (ValidationError, ValueError):
                raise _ProviderFallbackError("invalid_output")

        raise _ProviderFallbackError("invalid_output")

    async def _post_ollama(
        self,
        url: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            return await http_client.post(
                url,
                json=payload,
                timeout=timeout,
            )

    async def _call_ollama_once(
        self,
        base_url: str,
        model: str,
        user_prompt: str,
        timeout: float,
    ) -> list[str]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": TAG_SUGGEST_SYSTEM_PROMPT_V1},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        }
        try:
            resp = await self._post_ollama(
                f"{base_url}/api/chat",
                payload=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException:
            raise _ProviderFallbackError("timeout")
        except httpx.RequestError:
            raise _ProviderFallbackError("provider_unavailable")

        if resp.status_code == 429:
            raise _ProviderFallbackError("provider_rate_limited")
        if resp.status_code >= 400:
            raise _ProviderFallbackError("provider_unavailable")

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            raise _ProviderFallbackError("invalid_output")

        if not isinstance(data, dict):
            raise _ProviderFallbackError("invalid_output")

        msg = data.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise _ProviderFallbackError("invalid_output")

        try:
            validated = TagSuggestionModel.model_validate_json(content)
            return validated.tags
        except (ValidationError, ValueError):
            raise _ProviderFallbackError("invalid_output")

    async def suggest_tags(
        self,
        session: AsyncSession,
        user_id: str,
        title: str,
        url: str,
        content_markdown: str,
    ) -> TagSuggestion:
        start_time = time.monotonic()
        attempts = 0
        vocab_size = 0
        content_chars = len(content_markdown or "")

        def _finish(result: TagSuggestion) -> TagSuggestion:
            latency_ms = int(round((time.monotonic() - start_time) * 1000))
            reason_str = result.fallback_reason if result.fallback_reason else "-"
            logger.info(
                f"tags.suggest user_sub={user_id} source={result.source} "
                f"fallback_reason={reason_str} attempts={attempts} "
                f"vocab_size={vocab_size} content_chars={content_chars} "
                f"returned={len(result.tags)} reused={len(result.reused_existing)} "
                f"new={len(result.new_tags)} latency_ms={latency_ms}"
            )
            return result

        try:
            provider = get_configured_tagging_provider(validate_only=False)
        except ValueError:
            return _finish(
                TagSuggestion(
                    tags=[],
                    source="fallback",
                    fallback_reason="disabled",
                )
            )

        if provider == "off":
            return _finish(
                TagSuggestion(
                    tags=[],
                    source="fallback",
                    fallback_reason="disabled",
                )
            )

        openai_client: Optional[AsyncOpenAI] = None
        if provider == "openai":
            openai_client = _get_tagging_openai_client()
            if openai_client is None:
                return _finish(
                    TagSuggestion(
                        tags=[],
                        source="fallback",
                        fallback_reason="disabled",
                    )
                )

        deadline = (
            get_tag_suggest_ollama_deadline_seconds()
            if provider == "ollama"
            else get_tag_suggest_deadline_seconds()
        )
        deadline_at = start_time + deadline

        try:
            async with _async_timeout(deadline):
                raw_vocab = await self.management_service.get_tags(session, user_id)
                vocab = [
                    item
                    for item in (raw_vocab or [])
                    if isinstance(item.get("tag"), str)
                    and item["tag"]
                    and int(item.get("count", 0)) > 0
                ]
                vocab_size = len(vocab)

                vocab_block, _ = render_vocabulary_block(vocab)
                snippet_limit = get_tag_content_snippet_chars()
                content_chars = min(len(content_markdown or ""), snippet_limit)
                user_prompt = build_user_prompt(
                    title=title,
                    url=url,
                    content_markdown=content_markdown,
                    vocab_block=vocab_block,
                    content_snippet_chars=snippet_limit,
                )

                raw_tags: list[str] = []
                if provider == "openai":
                    assert openai_client is not None
                    model = get_tagging_llm_model()
                    for attempt in range(2):
                        remaining = deadline_at - time.monotonic()
                        if remaining <= 0:
                            raise asyncio.TimeoutError()
                        attempts += 1
                        try:
                            raw_tags = await self._call_openai_once(
                                client=openai_client,
                                model=model,
                                user_prompt=user_prompt,
                                timeout=remaining,
                            )
                            break
                        except RateLimitError:
                            raise _ProviderFallbackError("provider_rate_limited")
                        except APITimeoutError:
                            if attempt == 0 and (deadline_at - time.monotonic()) >= 1.0:
                                continue
                            raise _ProviderFallbackError("timeout")
                        except APIConnectionError:
                            if attempt == 0 and (deadline_at - time.monotonic()) >= 1.0:
                                continue
                            raise _ProviderFallbackError("provider_unavailable")
                        except APIStatusError as e:
                            if e.status_code == 429:
                                raise _ProviderFallbackError("provider_rate_limited")
                            if e.status_code >= 500:
                                if (
                                    attempt == 0
                                    and (deadline_at - time.monotonic()) >= 1.0
                                ):
                                    continue
                                raise _ProviderFallbackError("provider_unavailable")
                            raise _ProviderFallbackError("provider_unavailable")
                else:
                    # Ollama path: single attempt
                    remaining = deadline_at - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    attempts += 1
                    raw_tags = await self._call_ollama_once(
                        base_url=get_ollama_base_url(),
                        model=get_tagging_ollama_model(),
                        user_prompt=user_prompt,
                        timeout=remaining,
                    )

                tags, reused_existing, new_tags, all_rejected = normalize_and_map_tags(
                    raw_tags=raw_tags,
                    vocab=vocab,
                )
                if all_rejected:
                    raise _ProviderFallbackError("invalid_output")

                source_label = "llm" if provider == "openai" else "ollama"
                return _finish(
                    TagSuggestion(
                        tags=tags,
                        source=source_label,
                        reused_existing=reused_existing,
                        new_tags=new_tags,
                        fallback_reason=None,
                    )
                )

        except _ProviderFallbackError as fb:
            return _finish(
                TagSuggestion(
                    tags=[],
                    source="fallback",
                    fallback_reason=fb.reason,
                )
            )
        except (asyncio.TimeoutError, TimeoutError):
            return _finish(
                TagSuggestion(
                    tags=[],
                    source="fallback",
                    fallback_reason="timeout",
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
            return _finish(
                TagSuggestion(
                    tags=[],
                    source="fallback",
                    fallback_reason="internal_error",
                )
            )

