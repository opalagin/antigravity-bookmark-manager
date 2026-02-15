from database import engine
from sqlmodel import text
import asyncio

async def check_table():
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT * FROM allowed_users"))
            rows = result.fetchall()
            print("Table 'allowed_users' exists.")
            print(f"Row count: {len(rows)}")
            for row in rows:
                print(f" - {row}")
        except Exception as e:
            print(f"Error checking table: {e}")

if __name__ == "__main__":
    asyncio.run(check_table())
