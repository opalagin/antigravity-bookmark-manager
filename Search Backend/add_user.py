from database import engine
from models import AllowedUser, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
import asyncio
import sys

# Setup Async Session
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def add_user(email: str):
    if not email:
        print("Error: Email is required.")
        return

    print(f"Adding user: {email}...")
    
    async with async_session_factory() as session:
        # Check if exists
        existing = await session.get(AllowedUser, email)
        if existing:
            print(f"User '{email}' is already in the allowlist.")
            return

        user = AllowedUser(email=email)
        session.add(user)
        await session.commit()
        print(f"Successfully added '{email}' to allowed_users.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_user.py <email>")
    else:
        email = sys.argv[1]
        asyncio.run(add_user(email))
