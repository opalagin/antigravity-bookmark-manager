import asyncio
import os
import sys
from sqlmodel import text

# Add current directory to path so we can import database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine

async def prune_expired_tokens():
    """
    Deletes refresh tokens that have expired or been revoked for more than 30 days.
    """
    print("Connecting to database to prune old refresh tokens...")
    
    query = text("""
        DELETE FROM refresh_tokens
        WHERE expires_at < now() - INTERVAL '30 days'
           OR revoked_at < now() - INTERVAL '30 days'
    """)
    
    try:
        async with engine.begin() as conn:
            result = await conn.execute(query)
            pruned_count = result.rowcount
            print(f"Cleanup successful. Pruned {pruned_count} refresh token(s).")
    except Exception as e:
        print(f"Error during pruning: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(prune_expired_tokens())
