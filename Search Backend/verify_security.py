import asyncio
import os
import sys

# Ensure we can import from the backend directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 1. Set up a secure JWT_SECRET for testing if not already set, or validate it
if "JWT_SECRET" not in os.environ:
    os.environ["JWT_SECRET"] = "a" * 32
elif len(os.environ["JWT_SECRET"]) < 32:
    print("CRITICAL FAIL: JWT_SECRET is set but is shorter than 32 bytes.")
    sys.exit(1)

from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker
from database import engine
from models import AllowedUser, SQLModel
from main import app

# Setup Async Session
async_session_factory = async_sessionmaker(
    engine, expire_on_commit=False
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
    async with app.router.lifespan_context(app), AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        
        print("Starting Security Verification...")
        
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # Mock Response Object for external Google userinfo calls
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            
            # --- Scenario 1: Allowed User exchange Google Token & Access /bookmarks ---
            print("\n[Test] Exchange Google Token for JWT & Access /bookmarks")
            mock_resp.json.return_value = {"sub": "123", "email": "test@example.com"}
            
            # Request JWT session
            auth_response = await client.post(
                "/auth/google",
                json={"google_access_token": "google_token_123"},
            )
            print(f"Auth Response Code: {auth_response.status_code}")
            if auth_response.status_code != 200:
                print(f"FAIL: Google exchange failed. {auth_response.text}")
                sys.exit(1)
                
            auth_data = auth_response.json()
            access_token = auth_data["access_token"]
            refresh_token = auth_data["refresh_token"]
            print("PASS: Successfully exchanged Google token for JWT session.")
            
            # Attempt access to protected /bookmarks using the returned access JWT
            headers = {"Authorization": f"Bearer {access_token}"}
            payload = {
                "url": "http://example.com/1",
                "title": "Test 1",
                "content_markdown": "Content",
                "tags": []
            }
            
            response = await client.post("/bookmarks", json=payload, headers=headers)
            print(f"Bookmarks Response: {response.status_code}")
            if response.status_code == 200:
                print("PASS: Allowed user granted access via JWT.")
            else:
                print(f"FAIL: Allowed user denied. {response.text}")
                sys.exit(1)
                
            # --- Scenario 2: Disallowed User ---
            print("\n[Test] Disallowed User Authentication Check")
            mock_resp.json.return_value = {"sub": "456", "email": "bad@example.com"}
            
            bad_auth_response = await client.post(
                "/auth/google",
                json={"google_access_token": "google_token_456"},
            )
            print(f"Bad Auth Response Code: {bad_auth_response.status_code}")
            if bad_auth_response.status_code == 403:
                 print("PASS: Disallowed user denied JWT session creation.")
            else:
                  print(
                      "FAIL: Disallowed user granted JWT session creation. "
                      f"{bad_auth_response.text}"
                  )
                  sys.exit(1)

            # --- Scenario 3: Token Rotation ---
            print("\n[Test] Token Rotation")
            rotate_response = await client.post(
                "/auth/refresh", json={"refresh_token": refresh_token}
            )
            print(f"Rotate Response Code: {rotate_response.status_code}")
            if rotate_response.status_code == 200:
                print("PASS: Token rotation succeeded.")
                rotate_data = rotate_response.json()
                new_access_token = rotate_data["access_token"]
                new_refresh_token = rotate_data["refresh_token"]
            else:
                print(f"FAIL: Token rotation failed. {rotate_response.text}")
                sys.exit(1)
                
            # Test Reuse Detection (Old refresh token should be revoked and fail)
            print("\n[Test] Refresh Token Reuse Detection")
            reuse_response = await client.post(
                "/auth/refresh", json={"refresh_token": refresh_token}
            )
            print(f"Reuse Response Code: {reuse_response.status_code}")
            if reuse_response.status_code == 401:
                print("PASS: Reused refresh token rejected successfully.")
            else:
                print(
                    "FAIL: Reused refresh token was NOT rejected. "
                    f"Status: {reuse_response.status_code}"
                )
                sys.exit(1)

            # --- Scenario 4: Token Revocation / Logout ---
            print("\n[Test] Token Revocation / Logout")
            logout_response = await client.post(
                "/auth/logout", json={"refresh_token": new_refresh_token}
            )
            print(f"Logout Response Code: {logout_response.status_code}")
            if logout_response.status_code == 204:
                print("PASS: Logout request successfully executed.")
            else:
                print(
                    "FAIL: Logout request failed. "
                    f"Status: {logout_response.status_code}"
                )
                sys.exit(1)
                
            # Try to refresh again after logout - should fail
            refresh_after_logout = await client.post(
                "/auth/refresh", json={"refresh_token": new_refresh_token}
            )
            print(f"Refresh After Logout Code: {refresh_after_logout.status_code}")
            if refresh_after_logout.status_code == 401:
                print("PASS: Refresh after logout was rejected successfully.")
            else:
                print(
                    "FAIL: Refresh after logout succeeded! "
                    f"Status: {refresh_after_logout.status_code}"
                )
                sys.exit(1)

            # --- Scenario 5: Rate Limiting ---
            print("\n[Test] Rate Limiting (Flood /bookmarks)")
            # Flood using the new rotated access token (we need to generate a new
            # active session since we logged out the previous one)
            # Or wait, new_access_token was already issued before logout.
            # Logout only revokes the refresh token; the access token is stateless
            # and valid until expiry (1800s). So we reuse new_access_token.
            headers = {"Authorization": f"Bearer {new_access_token}"}
            triggered = False
            for i in range(15):
                payload["url"] = f"http://example.com/flood/{i}"
                response = await client.post(
                    "/bookmarks", json=payload, headers=headers
                )
                if response.status_code == 429:
                    print(f"PASS: Rate limit triggered at request #{i+1} of flood.")
                    triggered = True
                    break
            
            if not triggered:
                print("FAIL: Rate limit NOT triggered.")
                sys.exit(1)

            print("\nALL SECURITY VERIFICATIONS PASSED!")

if __name__ == "__main__":
    try:
        asyncio.run(run_tests_async())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
