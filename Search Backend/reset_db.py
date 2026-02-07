import asyncio
from database import engine
from models import SQLModel

async def reset_db():
    async with engine.begin() as conn:
        # Drop all tables
        await conn.run_sync(SQLModel.metadata.drop_all)
        # Create all tables
        await conn.run_sync(SQLModel.metadata.create_all)
    print("Database reset successfully.")

if __name__ == "__main__":
    asyncio.run(reset_db())
