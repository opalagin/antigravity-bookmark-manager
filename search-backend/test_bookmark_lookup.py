import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "a" * 32)

from httpx import ASGITransport, AsyncClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from database import get_session  # noqa: E402
from models import Bookmark  # noqa: E402


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        return self._rows[0]


class _FakeAsyncSession:
    """In-memory session that evaluates Select(Bookmark / Bookmark.url) predicates."""

    def __init__(self, bookmarks):
        self._bookmarks = bookmarks

    async def execute(self, stmt):
        compiled = stmt.compile()
        params = compiled.params
        user_id = params.get("user_id_1")
        url = params.get("url_1")

        matches = [b for b in self._bookmarks if b.user_id == user_id]
        if url is not None:
            matches = [b for b in matches if b.url == url]

        col_descs = stmt.column_descriptions
        if len(col_descs) == 1 and col_descs[0].get("name") == "url":
            return _FakeResult([b.url for b in matches])
        return _FakeResult(matches)


class TestBookmarkLookup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        main.limiter.reset()
        now = datetime.now(timezone.utc)
        self.bookmarks = [
            Bookmark(
                id=uuid4(),
                user_id="user_a",
                url="https://example.com/a",
                title="Page A",
                content_markdown="# Page A",
                tags=["docs", "ref"],
                created_at=now,
                updated_at=now,
            ),
            Bookmark(
                id=uuid4(),
                user_id="user_a",
                url="https://example.com/b",
                title="Page B",
                content_markdown="# Page B",
                tags=[],
                created_at=now,
                updated_at=now,
            ),
            Bookmark(
                id=uuid4(),
                user_id="user_b",
                url="https://example.com/secret",
                title="Secret",
                content_markdown="# Secret",
                tags=["private"],
                created_at=now,
                updated_at=now,
            ),
        ]

        fake_session = _FakeAsyncSession(self.bookmarks)

        async def _fake_session():
            yield fake_session

        main.app.dependency_overrides[get_session] = _fake_session

    async def asyncTearDown(self):
        main.app.dependency_overrides.clear()

    def _auth_headers(self, sub: str, email: str = "u@example.com"):
        token = auth.create_access_token(sub, email)
        return {"Authorization": f"Bearer {token}"}

    async def test_get_bookmark_urls_scoped_to_owner(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/bookmarks/urls", headers=self._auth_headers("user_a")
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(
                data["urls"], ["https://example.com/a", "https://example.com/b"]
            )
            self.assertEqual(data["count"], 2)
            self.assertNotIn("https://example.com/secret", data["urls"])

            resp_b = await client.get(
                "/bookmarks/urls", headers=self._auth_headers("user_b")
            )
            self.assertEqual(resp_b.status_code, 200)
            self.assertEqual(
                resp_b.json(),
                {"urls": ["https://example.com/secret"], "count": 1},
            )

    async def test_lookup_exact_match_and_isolation(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Exact match succeeds and omits content_markdown
            resp = await client.post(
                "/bookmarks/lookup",
                json={"url": "https://example.com/a"},
                headers=self._auth_headers("user_a"),
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["url"], "https://example.com/a")
            self.assertEqual(data["title"], "Page A")
            self.assertEqual(data["tags"], ["docs", "ref"])
            self.assertIsNone(data["content_markdown"])

            # Trailing slash is not a match (exact match only)
            resp_slash = await client.post(
                "/bookmarks/lookup",
                json={"url": "https://example.com/a/"},
                headers=self._auth_headers("user_a"),
            )
            self.assertEqual(resp_slash.status_code, 404)
            self.assertEqual(resp_slash.json()["detail"], "Not bookmarked")

            # Other user's bookmark is 404 for user_a
            resp_other = await client.post(
                "/bookmarks/lookup",
                json={"url": "https://example.com/secret"},
                headers=self._auth_headers("user_a"),
            )
            self.assertEqual(resp_other.status_code, 404)
            self.assertEqual(resp_other.json()["detail"], "Not bookmarked")

    async def test_lookup_422_on_overlong_url(self):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            overlong_url = "https://example.com/" + ("x" * 2048)
            resp = await client.post(
                "/bookmarks/lookup",
                json={"url": overlong_url},
                headers=self._auth_headers("user_a"),
            )
            self.assertEqual(resp.status_code, 422)


async def run_all():
    suite = TestBookmarkLookup()
    for name in [
        "test_get_bookmark_urls_scoped_to_owner",
        "test_lookup_exact_match_and_isolation",
        "test_lookup_422_on_overlong_url",
    ]:
        print(f"[RUN] {name} ...", flush=True)
        await suite.asyncSetUp()
        try:
            await getattr(suite, name)()
        finally:
            await suite.asyncTearDown()
        print(f"[PASS] {name}", flush=True)
    print("ALL BOOKMARK LOOKUP TESTS PASSED!", flush=True)


if __name__ == "__main__":
    asyncio.run(run_all())
