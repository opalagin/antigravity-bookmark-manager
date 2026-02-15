import asyncio
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx import ASGITransport
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from database import engine
from models import AllowedUser, SQLModel
from main import app

# Setup Async Session
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

async def setup_data():
    async with async_session_factory() as session:
         user = AllowedUser(email="test@example.com")
         session.add(user)
         await session.commit()

async def run_tests_async():
    # 1. Reset DB and Setup Data
    await reset_db()
    await setup_data()
    
    # 2. Async Client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
    
        # Data
        valid_token = "valid_token"
        headers = {"Authorization": f"Bearer {valid_token}"}
        
        print("Starting Security Verification...")
        
        with patch("requests.get") as mock_get:
            # Mock Response Object
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            
            # --- Scenario 1: Allowed User ---
            print("\n[Test] Allowed User Access (Limit 10/min)")
            mock_resp.json.return_value = {"sub": "123", "email": "test@example.com"}
            
            payload = {
                "url": "http://example.com/1",
                "title": "Test 1",
                "content_markdown": "Content",
                "tags": []
            }
            
            response = await client.post("/bookmarks", json=payload, headers=headers)
            print(f"Response: {response.status_code}")
            if response.status_code == 200:
                print("PASS: Allowed user granted access.")
            else:
                print(f"FAIL: Allowed user denied. {response.text}")
                
            # --- Scenario 2: Disallowed User ---
            print("\n[Test] Disallowed User Access")
            mock_resp.json.return_value = {"sub": "456", "email": "bad@example.com"}
            
            payload["url"] = "http://example.com/2"
            response = await client.post("/bookmarks", json=payload, headers=headers)
            print(f"Response: {response.status_code}")
            if response.status_code == 403:
                 print("PASS: Disallowed user denied access.")
            else:
                 print(f"FAIL: Disallowed user granted access. {response.text}")

            # --- Scenario 3: Rate Limiting ---
            print("\n[Test] Rate Limiting (Flood /bookmarks)")
            # Reset to Allowed User
            mock_resp.json.return_value = {"sub": "123", "email": "test@example.com"}
            
            # We sent 1 successful request above.
            # Limit is 10/min.
            # Send 11 more (Total 12).
            
            triggered = False
            for i in range(15):
                payload["url"] = f"http://example.com/flood/{i}"
                response = await client.post("/bookmarks", json=payload, headers=headers)
                if response.status_code == 429:
                    print(f"PASS: Rate limit triggered at request #{i+2} (Total).")
                    triggered = True
                    break
            
            if not triggered:
                print("FAIL: Rate limit NOT triggered.")

if __name__ == "__main__":
    try:
        asyncio.run(run_tests_async())
    except Exception as e:
        import traceback
        traceback.print_exc()
