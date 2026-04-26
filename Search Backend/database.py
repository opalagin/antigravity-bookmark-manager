import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker

# Railway injects DATABASE_URL as a single connection string.
# Local Docker Compose uses individual POSTGRES_* vars.
# We prefer DATABASE_URL if set, falling back to individual vars.
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Railway (and most PaaS) emit postgres:// or postgresql:// schemes.
    # asyncpg requires postgresql+asyncpg://.
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    POSTGRES_USER = os.getenv("POSTGRES_USER", "bookmark_user")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "secure_password_here")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "bookmarks_db")
    DATABASE_URL = (
        f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

engine = create_async_engine(DATABASE_URL, echo=False, future=True)


async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
