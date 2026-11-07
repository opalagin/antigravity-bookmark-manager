import asyncio
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "a" * 32)

import httpx  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from openai import (  # noqa: E402
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)

import auth  # noqa: E402
import main  # noqa: E402
import tagging  # noqa: E402
from database import get_session  # noqa: E402
from models import Bookmark  # noqa: E402


def _make_openai_response(tags=None, refusal=None, finish_reason="stop", content=None):
    parsed = tagging.TagSuggestionModel(tags=tags) if tags is not None else None
    msg = SimpleNamespace(parsed=parsed, refusal=refusal, content=content)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class TestAutoTagging(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Reset rate limiter storage before each test
        main.limiter.reset()
        tagging._tagging_openai_client = None
        tagging._tagging_openai_key = None

        async def _fake_session():
            yield MagicMock()

        main.app.dependency_overrides[get_session] = _fake_session

    async def asyncTearDown(self):
        main.app.dependency_overrides.clear()

    def _auth_headers(self, sub: str = "user_1", email: str = "u1@example.com"):
        token = auth.create_access_token(sub, email)
        return {"Authorization": f"Bearer {token}"}

    # --- Phase 1: Normalizer and mapping ---

    async def test_normalizer_and_mapping_acceptance(self):
        # 1. Vocabulary ["React"] + model "react" -> ["React"], reused=["React"], new=[]
        tags, reused, new, all_rej = tagging.normalize_and_map_tags(
            ["react"], [{"tag": "React", "count": 2}]
        )
        self.assertEqual(tags, ["React"])
        self.assertEqual(reused, ["React"])
        self.assertEqual(new, [])
        self.assertFalse(all_rej)

        # 2. Vocabulary ["React" (3), "react" (5)] + model "REACT" -> ["react"]
        tags, reused, new, _ = tagging.normalize_and_map_tags(
            ["REACT"],
            [{"tag": "React", "count": 3}, {"tag": "react", "count": 5}],
        )
        self.assertEqual(tags, ["react"])
        self.assertEqual(reused, ["react"])

        # On a tie, lexicographically smallest wins ("React" < "react")
        tags, reused, new, _ = tagging.normalize_and_map_tags(
            ["REACT"],
            [{"tag": "react", "count": 4}, {"tag": "React", "count": 4}],
        )
        self.assertEqual(tags, ["React"])
        self.assertEqual(reused, ["React"])

        # 3. Model returns Café, 機械学習, программирование/rust -> kept lowered
        tags, reused, new, all_rej = tagging.normalize_and_map_tags(
            ["Café", "機械学習", "программирование/rust"], []
        )
        self.assertEqual(tags, ["café", "機械学習", "программирование/rust"])
        self.assertEqual(new, ["café", "機械学習", "программирование/rust"])
        self.assertFalse(all_rej)

        # 4. Model returns c++ -> rejected (not stripped to c)
        self.assertIsNone(tagging.clean_proposed_tag("c++"))
        tags, reused, new, all_rej = tagging.normalize_and_map_tags(["c++"], [])
        self.assertEqual(tags, [])
        self.assertTrue(all_rej)

        # 5. Vocabulary ["Straße"] + model "strasse" -> ["Straße"]
        tags, reused, new, all_rej = tagging.normalize_and_map_tags(
            ["strasse"], [{"tag": "Straße", "count": 1}]
        )
        self.assertEqual(tags, ["Straße"])
        self.assertEqual(reused, ["Straße"])
        self.assertEqual(new, [])
        self.assertFalse(all_rej)

        # New tag with ß keeps ß (lower() rather than casefold())
        tags, _, new, _ = tagging.normalize_and_map_tags(["Straße"], [])
        self.assertEqual(tags, ["straße"])
        self.assertEqual(new, ["straße"])

        # 6. Stored tags are byte-identical before and after any suggest call
        stored_vocab = [{"tag": "Work/Projects_V1", "count": 3}]
        vocab_snapshot = [dict(x) for x in stored_vocab]
        tags, reused, new, _ = tagging.normalize_and_map_tags(
            ["work/projects-v1"], stored_vocab
        )
        self.assertEqual(tags, ["Work/Projects_V1"])
        self.assertEqual(stored_vocab, vocab_snapshot)

    # --- Phase 1: Provider failure handling, deadline, retries ---

    async def test_provider_failures_and_retries(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = self._auth_headers("sub_fail_test")
            req_body = {
                "url": "https://example.com/post",
                "title": "Test Article",
                "content_markdown": "Some content about distributed systems.",
            }

            # a) Provider disabled / no key -> disabled
            with patch.dict(
                os.environ,
                {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": ""},
                clear=False,
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["tags"], [])
                self.assertEqual(data["source"], "fallback")
                self.assertEqual(data["fallback_reason"], "disabled")

            with patch.dict(os.environ, {"TAGGING_LLM_PROVIDER": "off"}, clear=False):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "disabled")

            # b) Deadline exceeded: sleep 10 s -> returns within deadline + 0.2 s
            cancelled_observed = False

            async def _slow_parse(**kwargs):
                nonlocal cancelled_observed
                try:
                    await asyncio.sleep(10.0)
                except asyncio.CancelledError:
                    cancelled_observed = True
                    raise

            mock_oai = MagicMock()
            mock_oai.beta.chat.completions.parse = AsyncMock(side_effect=_slow_parse)

            with (
                patch.dict(
                    os.environ,
                    {
                        "TAGGING_LLM_PROVIDER": "openai",
                        "OPENAI_API_KEY": "sk-test",
                        "TAG_SUGGEST_DEADLINE_SECONDS": "0.3",
                    },
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                t0 = time.monotonic()
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                elapsed = time.monotonic() - t0
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "timeout")
                self.assertLess(elapsed, 0.3 + 0.2)
                self.assertTrue(cancelled_observed)

            # c) 429 from provider -> 1 attempt, fallback="provider_rate_limited"
            mock_req = httpx.Request(
                "POST", "https://api.openai.com/v1/chat/completions"
            )
            mock_resp_429 = httpx.Response(429, request=mock_req)
            err_429 = RateLimitError(
                "Rate limit reached", response=mock_resp_429, body=None
            )
            mock_oai_429 = MagicMock()
            mock_oai_429.beta.chat.completions.parse = AsyncMock(side_effect=err_429)

            with (
                patch.dict(
                    os.environ,
                    {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_429
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(
                    resp.json()["fallback_reason"], "provider_rate_limited"
                )
                self.assertEqual(
                    mock_oai_429.beta.chat.completions.parse.call_count, 1
                )

            # d) Connection error -> 2 attempts, fallback="provider_unavailable"
            err_conn = APIConnectionError(request=mock_req)
            mock_oai_conn = MagicMock()
            mock_oai_conn.beta.chat.completions.parse = AsyncMock(side_effect=err_conn)

            with (
                patch.dict(
                    os.environ,
                    {
                        "TAGGING_LLM_PROVIDER": "openai",
                        "OPENAI_API_KEY": "sk-test",
                        "TAG_SUGGEST_DEADLINE_SECONDS": "3.5",
                    },
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_conn
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "provider_unavailable")
                self.assertEqual(
                    mock_oai_conn.beta.chat.completions.parse.call_count, 2
                )

            # e) HTTP 5xx after retry -> provider_unavailable
            mock_resp_503 = httpx.Response(503, request=mock_req)
            err_503 = APIStatusError(
                "Service Unavailable", response=mock_resp_503, body=None
            )
            mock_oai_503 = MagicMock()
            mock_oai_503.beta.chat.completions.parse = AsyncMock(side_effect=err_503)

            with (
                patch.dict(
                    os.environ,
                    {
                        "TAGGING_LLM_PROVIDER": "openai",
                        "OPENAI_API_KEY": "sk-test",
                        "TAG_SUGGEST_DEADLINE_SECONDS": "3.5",
                    },
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_503
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "provider_unavailable")
                self.assertEqual(
                    mock_oai_503.beta.chat.completions.parse.call_count, 2
                )

            # f) Structured-output refusal -> refused
            mock_oai_refused = MagicMock()
            mock_oai_refused.beta.chat.completions.parse = AsyncMock(
                return_value=_make_openai_response(
                    tags=None, refusal="Cannot process this content."
                )
            )
            with (
                patch.dict(
                    os.environ,
                    {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_refused
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "refused")

            # g) Every tag rejected by §5.6 -> invalid_output
            mock_oai_invalid = MagicMock()
            mock_oai_invalid.beta.chat.completions.parse = AsyncMock(
                return_value=_make_openai_response(tags=["c++", "???"])
            )
            with (
                patch.dict(
                    os.environ,
                    {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_invalid
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "invalid_output")

            # h) Unexpected exception -> internal_error
            mock_oai_boom = MagicMock()
            mock_oai_boom.beta.chat.completions.parse = AsyncMock(
                side_effect=RuntimeError("unexpected failure")
            )
            with (
                patch.dict(
                    os.environ,
                    {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_boom
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = await client.post(
                    "/tags/suggest", json=req_body, headers=headers
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "internal_error")

    # --- Phase 1: Input bounds ---

    async def test_input_bounds_and_vocab_cap(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = self._auth_headers("sub_bounds_test")

            # 1. 300 KiB body with Content-Length -> 413
            prefix = b'{"url":"https://example.com","title":"t","content_markdown":"'
            large_body = prefix + (b"a" * (300 * 1024)) + b'"}'
            resp = await client.post(
                "/tags/suggest",
                content=large_body,
                headers={**headers, "Content-Type": "application/json"},
            )
            self.assertEqual(resp.status_code, 413)

            # 2. 300 KiB chunked body without Content-Length -> 413
            async def _chunked_stream():
                for _ in range(30):
                    yield b"x" * 10240

            resp_chunked = await client.post(
                "/tags/suggest",
                content=_chunked_stream(),
                headers={**headers, "Content-Type": "application/json"},
            )
            self.assertEqual(resp_chunked.status_code, 413)

            # 3. title of 513 chars -> 422
            resp_422 = await client.post(
                "/tags/suggest",
                json={
                    "url": "https://example.com",
                    "title": "a" * 513,
                    "content_markdown": "hello",
                },
                headers=headers,
            )
            self.assertEqual(resp_422.status_code, 422)

            # 4. Vocab of 5000 long tags -> rendered vocab block <= TAG_VOCAB_MAX_CHARS
            huge_vocab = [
                {"tag": f"category-{i:04d}/subtag-{'x' * 50}", "count": 5000 - i}
                for i in range(5000)
            ]
            vocab_block, count = tagging.render_vocabulary_block(
                huge_vocab, vocab_max=200, vocab_max_chars=8000
            )
            self.assertLessEqual(len(vocab_block), 8000)
            self.assertGreater(count, 0)
            self.assertLessEqual(count, 200)

    # --- Phase 1: Per-user rate limit ---

    async def test_user_rate_limit_isolation(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers_u1 = self._auth_headers("user_alpha", "alpha@example.com")
            headers_u2 = self._auth_headers("user_beta", "beta@example.com")
            body = {
                "url": "https://example.com",
                "title": "Rate limit test",
                "content_markdown": "Content",
            }

            with patch.dict(os.environ, {"TAGGING_LLM_PROVIDER": "off"}, clear=False):
                for _ in range(20):
                    r1 = await client.post(
                        "/tags/suggest", json=body, headers=headers_u1
                    )
                    self.assertEqual(r1.status_code, 200)

                # 21st request for user_alpha -> 429
                r1_21 = await client.post(
                    "/tags/suggest", json=body, headers=headers_u1
                )
                self.assertEqual(r1_21.status_code, 429)

                # user_beta from the same IP still gets 200 for all 20 of their requests
                for _ in range(20):
                    r2 = await client.post(
                        "/tags/suggest", json=body, headers=headers_u2
                    )
                    self.assertEqual(r2.status_code, 200)

    # --- Phase 2: Ollama path, config endpoint, startup validation ---

    async def test_ollama_and_config(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = self._auth_headers("sub_ollama")
            body = {
                "url": "https://example.com/rust",
                "title": "Rust Async",
                "content_markdown": "Tokio and futures in Rust.",
            }

            # 1. GET /config reflects active deadline
            with patch.dict(
                os.environ,
                {
                    "TAGGING_LLM_PROVIDER": "openai",
                    "TAG_SUGGEST_DEADLINE_SECONDS": "3.5",
                },
                clear=False,
            ):
                cfg = await client.get("/config")
                self.assertEqual(cfg.status_code, 200)
                self.assertEqual(cfg.json()["tag_suggest_timeout_ms"], 4000)

            with patch.dict(
                os.environ,
                {
                    "TAGGING_LLM_PROVIDER": "ollama",
                    "TAG_SUGGEST_OLLAMA_DEADLINE_SECONDS": "10",
                },
                clear=False,
            ):
                cfg = await client.get("/config")
                self.assertEqual(cfg.status_code, 200)
                self.assertEqual(cfg.json()["tag_suggest_timeout_ms"], 10500)

            # 2. Ollama returning non-JSON or schema-violating JSON -> invalid_output
            mock_bad_json_resp = MagicMock()
            mock_bad_json_resp.status_code = 200
            mock_bad_json_resp.json.return_value = {
                "message": {"content": "not valid json {"}
            }

            with (
                patch.dict(os.environ, {"TAGGING_LLM_PROVIDER": "ollama"}, clear=False),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    main.tagging_service,
                    "_post_ollama",
                    new=AsyncMock(return_value=mock_bad_json_resp),
                ),
            ):
                resp = await client.post("/tags/suggest", json=body, headers=headers)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "invalid_output")

            mock_bad_schema_resp = MagicMock()
            mock_bad_schema_resp.status_code = 200
            mock_bad_schema_resp.json.return_value = {
                "message": {"content": '{"wrong_key": 123}'}
            }
            with (
                patch.dict(os.environ, {"TAGGING_LLM_PROVIDER": "ollama"}, clear=False),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    main.tagging_service,
                    "_post_ollama",
                    new=AsyncMock(return_value=mock_bad_schema_resp),
                ),
            ):
                resp = await client.post("/tags/suggest", json=body, headers=headers)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "invalid_output")

            # 3. Ollama unreachable -> provider_unavailable
            with (
                patch.dict(
                    os.environ,
                    {
                        "TAGGING_LLM_PROVIDER": "ollama",
                        "TAG_SUGGEST_OLLAMA_DEADLINE_SECONDS": "1.0",
                    },
                    clear=False,
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    main.tagging_service,
                    "_post_ollama",
                    new=AsyncMock(
                        side_effect=httpx.ConnectError("Connection refused")
                    ),
                ),
            ):
                resp = await client.post("/tags/suggest", json=body, headers=headers)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["fallback_reason"], "provider_unavailable")

            # 4. Ollama success path
            mock_ok_resp = MagicMock()
            mock_ok_resp.status_code = 200
            mock_ok_resp.json.return_value = {
                "message": {"content": '{"tags": ["Rust", "async-io"]}'}
            }
            with (
                patch.dict(os.environ, {"TAGGING_LLM_PROVIDER": "ollama"}, clear=False),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[{"tag": "rust", "count": 5}]),
                ),
                patch.object(
                    main.tagging_service,
                    "_post_ollama",
                    new=AsyncMock(return_value=mock_ok_resp),
                ),
            ):
                resp = await client.post("/tags/suggest", json=body, headers=headers)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["source"], "ollama")
                self.assertEqual(data["tags"], ["rust", "async-io"])
                self.assertEqual(data["reused_existing"], ["rust"])
                self.assertEqual(data["new_tags"], ["async-io"])

            # 5. Unknown provider value -> startup validation fails
            with patch.dict(
                os.environ, {"TAGGING_LLM_PROVIDER": "unknown_llm"}, clear=False
            ):
                with self.assertRaises(ValueError):
                    tagging.validate_tagging_config()

    # --- Phase 4: Server-side auto_tag flag ---

    async def test_auto_tag_flag_on_ingest(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = self._auth_headers("sub_autotag")

            async def _fake_process_bookmark(
                session, user_id, url, title, content, tags
            ):
                return Bookmark(
                    user_id=user_id,
                    url=url,
                    title=title,
                    content_markdown=content,
                    tags=tags,
                )

            # 1. Provider times out with auto_tag: true -> fallback:timeout
            async def _slow_parse(**kwargs):
                await asyncio.sleep(5.0)

            mock_oai = MagicMock()
            mock_oai.beta.chat.completions.parse = AsyncMock(side_effect=_slow_parse)

            with (
                patch.dict(
                    os.environ,
                    {
                        "TAGGING_LLM_PROVIDER": "openai",
                        "OPENAI_API_KEY": "sk-test",
                        "TAG_SUGGEST_DEADLINE_SECONDS": "0.2",
                    },
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    main.ingestion_service,
                    "process_bookmark",
                    new=AsyncMock(side_effect=_fake_process_bookmark),
                ),
            ):
                t0 = time.monotonic()
                resp = await client.post(
                    "/bookmarks",
                    json={
                        "url": "https://example.com/1",
                        "title": "Timeout AutoTag",
                        "content_markdown": "Content",
                        "tags": [],
                        "auto_tag": True,
                    },
                    headers=headers,
                )
                elapsed = time.monotonic() - t0
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["tags"], [])
                self.assertEqual(data["auto_tag_status"], "fallback:timeout")
                self.assertLess(elapsed, 0.5)

            # 2. With non-empty tags, provider is never called (status: "skipped")
            mock_suggest = AsyncMock()
            with (
                patch.object(main.tagging_service, "suggest_tags", new=mock_suggest),
                patch.object(
                    main.ingestion_service,
                    "process_bookmark",
                    new=AsyncMock(side_effect=_fake_process_bookmark),
                ),
            ):
                resp = await client.post(
                    "/bookmarks",
                    json={
                        "url": "https://example.com/2",
                        "title": "Explicit Tags",
                        "content_markdown": "Content",
                        "tags": ["manual-tag"],
                        "auto_tag": True,
                    },
                    headers=headers,
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["tags"], ["manual-tag"])
                self.assertEqual(data["auto_tag_status"], "skipped")
                mock_suggest.assert_not_called()

            # 3. With auto_tag: true and empty tags, applied when provider succeeds
            mock_oai_ok = MagicMock()
            mock_oai_ok.beta.chat.completions.parse = AsyncMock(
                return_value=_make_openai_response(tags=["python", "fastapi"])
            )
            with (
                patch.dict(
                    os.environ,
                    {"TAGGING_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
                    clear=False,
                ),
                patch.object(
                    tagging, "_get_tagging_openai_client", return_value=mock_oai_ok
                ),
                patch.object(
                    main.management_service,
                    "get_tags",
                    new=AsyncMock(return_value=[{"tag": "python", "count": 4}]),
                ),
                patch.object(
                    main.ingestion_service,
                    "process_bookmark",
                    new=AsyncMock(side_effect=_fake_process_bookmark),
                ),
            ):
                resp = await client.post(
                    "/bookmarks",
                    json={
                        "url": "https://example.com/3",
                        "title": "FastAPI Guide",
                        "content_markdown": "Building APIs with FastAPI.",
                        "tags": [],
                        "auto_tag": True,
                    },
                    headers=headers,
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["tags"], ["python", "fastapi"])
                self.assertEqual(data["auto_tag_status"], "applied")


async def run_all():
    suite = TestAutoTagging()
    for name in [
        "test_normalizer_and_mapping_acceptance",
        "test_provider_failures_and_retries",
        "test_input_bounds_and_vocab_cap",
        "test_user_rate_limit_isolation",
        "test_ollama_and_config",
        "test_auto_tag_flag_on_ingest",
    ]:
        print(f"[RUN] {name} ...", flush=True)
        await suite.asyncSetUp()
        try:
            await getattr(suite, name)()
        finally:
            await suite.asyncTearDown()
        print(f"[PASS] {name}", flush=True)
    print("ALL BACKEND AUTO-TAGGING TESTS PASSED!", flush=True)


if __name__ == "__main__":
    asyncio.run(run_all())
