#!/usr/bin/env python3
"""
One-shot script to initialize the Railway Postgres schema and seed allowed_users.
Run: python setup_railway_db.py
Requires DATABASE_URL environment variable pointing to the Railway Postgres public URL.
"""
import asyncio
import asyncpg
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:FBdmpyfZnZkowTykqPMwPxheEgwwohuL@nozomi.proxy.rlwy.net:49749/railway"
)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    content_markdown TEXT,
    tags TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_url UNIQUE (user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks(user_id);

CREATE TABLE IF NOT EXISTS bookmark_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bookmark_id UUID REFERENCES bookmarks(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(384)
);
CREATE INDEX IF NOT EXISTS embedding_idx
    ON bookmark_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_bookmark_embeddings_bookmark_id
    ON bookmark_embeddings(bookmark_id);

CREATE TABLE IF NOT EXISTS allowed_users (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
"""

SEED_EMAILS = ["alex.palagin@gmail.com"]


async def main():
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to Railway Postgres...")
    conn = await asyncpg.connect(url)
    try:
        print("Running schema init...")
        await conn.execute(SCHEMA_SQL)
        print("  [OK] Schema initialized (idempotent)")

        for email in SEED_EMAILS:
            await conn.execute(
                "INSERT INTO allowed_users (email) VALUES ($1) ON CONFLICT (email) DO NOTHING",
                email,
            )
            print(f"  [OK] Seeded allowed user: {email}")
    finally:
        await conn.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
