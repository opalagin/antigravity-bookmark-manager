#!/usr/bin/env python3
"""
One-shot script to seed the allowed_users table on Railway Postgres.

Usage:
    Set DATABASE_URL env var, then run:
    python seed_allowed_users.py

The PILOT_MODE_EMAILS env var (comma-separated) overrides the default list.
"""
import asyncio
import os

import asyncpg

# Default seed list — override via PILOT_MODE_EMAILS env var
DEFAULT_EMAILS = ["alex.palagin@gmail.com"]

EMAILS = [
    e.strip()
    for e in os.getenv("PILOT_MODE_EMAILS", ",".join(DEFAULT_EMAILS)).split(",")
    if e.strip()
]


async def seed() -> None:
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")

    # asyncpg uses postgresql:// (not postgresql+asyncpg://)
    url = (
        raw_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )

    print(f"Connecting to database…")
    conn = await asyncpg.connect(url)
    try:
        for email in EMAILS:
            await conn.execute(
                """
                INSERT INTO allowed_users (email)
                VALUES ($1)
                ON CONFLICT (email) DO NOTHING
                """,
                email,
            )
            print(f"  ✅ Seeded: {email}")
    finally:
        await conn.close()

    print("\nSeeding complete.")


if __name__ == "__main__":
    asyncio.run(seed())
