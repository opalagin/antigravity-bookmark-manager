# Backend-Issued JWT Authentication — Specification

Status: Draft
Author: brainstorm with Claude
Date: 2026-05-23

## 1. Goal

Replace direct use of Google OAuth access tokens as the Search Backend's API credential with a **backend-issued JWT** session, so that:

1. Users stay signed in for weeks/months on each device, not ~1 hour.
2. Signing in on one device does **not** invalidate sessions on any other device.
3. Token validation no longer requires a network round trip to Google on every API call.
4. A future "log out everywhere" / device-revocation capability is possible without re-architecting again.

Google remains the **identity provider**. We keep using `chrome.identity.launchWebAuthFlow` to obtain a Google identity assertion. What changes is that the Google token is exchanged once, on the backend, for our own session JWT — and from that point on, the extension never sends a Google token again.

## 2. Motivation

Today's auth has three concrete problems, all visible in `Search Backend/main.py:199-209`:

- The extension stores the raw Google **access token** returned by the OAuth 2.0 implicit flow (`Chrome Plugin/popup.js:255`, `Firefox Plugin/popup.js:327`, `response_type=token`). Google expires these in ~3600 seconds. There is no refresh token (implicit flow does not issue one), no silent renewal, and no expiry check on the client. The first API call after expiry raises `Error: Invalid Authentication Token` (line 209) and the user must manually re-click "Login with Google".
- Every authenticated request makes a synchronous HTTPS call to `https://www.googleapis.com/oauth2/v3/userinfo` (`main.py:199`). That is one extra round trip per request, subject to Google rate limits, and a hard dependency on Google's availability for our backend to function.
- "Multi-device" today works only by accident. Each device runs `launchWebAuthFlow` independently and gets its own short-lived Google access token. Devices do not invalidate each other, but they also share no notion of a session — so user-perceived "logouts" (the 1-hour expiry firing on each device on its own schedule) feel like devices kicking each other out.

The user's stated requirement — *"logged in on all my devices for longer times and they don't logout each other"* — is not solvable by tuning the current flow. Google access tokens cannot be made longer-lived; the lifetime is set by Google. The fix is to stop using them as the API credential.

## 3. Non-goals

- Not replacing Google as the identity provider. Login still goes through `accounts.google.com`.
- Not switching to the OAuth 2.0 **authorization code flow with PKCE**. That flow would give us a Google refresh token, but (a) it requires significantly more extension plumbing, (b) refresh tokens for Chrome extensions sit in non-trivial territory around `client_secret`/PKCE, and (c) it still keeps Google in the request path for the refresh exchange. Backend-issued JWTs are simpler and give us strictly more control.
- Not introducing user-visible session management UI in v1 (no "active devices" list, no per-device names). The data model should support adding it later, but the v1 UI is just login/logout on the current device.
- Not adding 2FA / step-up auth. Google handles MFA upstream of us.
- Not introducing roles / scopes. The single existing authorization check (`AllowedUser` allowlist, `main.py:226-235`) still applies and is unchanged.
- Not changing the pilot-mode allowlist mechanism. The check moves from per-request to per-login (see §5.5).

## 4. Current state (reference)

- `Search Backend/main.py:182-183` — `HTTPBearer()` dependency named `security`; every protected route depends on `get_current_user`.
- `Search Backend/main.py:187-249` — `get_current_user`:
  - Reads `Authorization: Bearer <token>` from the request.
  - Calls Google's `userinfo` endpoint to validate.
  - On 200, extracts `sub` and `email`, checks `AllowedUser` allowlist, returns `sub` as the user id.
  - On non-200, raises HTTP 401 with detail `"Invalid Authentication Token. Status: ..."` — this is the error the user reports.
  - Has a mock-auth fallback for tokens starting with `user_` (development convenience).
- `Search Backend/main.py:185, 199` — uses the lifespan-scoped `httpx.AsyncClient` (`app.state.http`).
- `Search Backend/models.py:66-72` — `AllowedUser` table, keyed by `email`.
- `Search Backend/requirements.txt` — does **not** currently include a JWT library.
- `Chrome Plugin/api.js:1-89` — single global `api` object. Stores `token` in memory; persistent copy lives in `chrome.storage.local` under key `authToken`. `_fetch` attaches `Authorization: Bearer ${this.token}` and treats 401 as a terminal error (just throws "Unauthorized").
- `Chrome Plugin/popup.js:247-291` — login flow: `launchWebAuthFlow` against `accounts.google.com/o/oauth2/v2/auth` with `response_type=token`, scopes `openid email profile`. Token parsed out of the redirect URL hash and persisted.
- `Firefox Plugin/popup.js:319-359` — mirror of the Chrome flow, against `browser.identity.launchWebAuthFlow`. Identical scopes and parameters.
- `Chrome Plugin/sidebar.js`, `Chrome Plugin/popup.js`, `Firefox Plugin/sidebar.js`, `Firefox Plugin/popup.js`, `Firefox Plugin/manager.js` all hydrate `api.token` from `chrome.storage.local.authToken` on load (Firefox uses `browser.storage.local`). MV3 service worker / background.js does not currently participate in auth.

## 5. Design

### 5.1 Flow overview

```
+-----------+  1. launchWebAuthFlow (Google, scope=openid email)
| Extension | ----------------------------------------------------> Google
|           |  2. Google access token (short-lived, throwaway)
|           | <----------------------------------------------------
|           |
|           |  3. POST /auth/google  { google_access_token }
|           | ----------------------------------------------------> Backend
|           |  4. { access_jwt, refresh_jwt, expires_in,
|           |       user: { sub, email } }
|           | <----------------------------------------------------
|           |
|           |  5..N. API call with Authorization: Bearer <access_jwt>
|           | ----------------------------------------------------> Backend
|           |        Backend verifies JWT locally; no Google round-trip.
|           |
|           |  On 401 (access_jwt expired):
|           |  POST /auth/refresh  { refresh_jwt }
|           | ----------------------------------------------------> Backend
|           |  { access_jwt, refresh_jwt }   (refresh rotated)
|           | <----------------------------------------------------
+-----------+
```

The Google access token from step 2 is **used exactly once** (to prove identity to our backend) and then discarded. It is not persisted in `chrome.storage.local` anymore.

### 5.2 Tokens

Two JWTs, both HS256-signed with a server secret `JWT_SECRET` held in env.

**Access JWT**
- Lifetime: `JWT_ACCESS_TTL_SECONDS`, default **1800** (30 min).
- Claims:
  - `sub` — Google `sub` (immutable user id). Same value `get_current_user` returns today.
  - `email` — for logging / allowlist; not re-validated per request.
  - `iat`, `exp`, `iss="smart-bookmark-manager"`, `aud="api"`.
  - `typ="access"`.
- Sent on every API call. Verified locally — no DB hit, no Google hit.

**Refresh JWT**
- Lifetime: `JWT_REFRESH_TTL_SECONDS`, default **7776000** (90 days).
- Claims as above plus `typ="refresh"` and `jti` (UUID, the refresh-token id).
- Sent **only** to `/auth/refresh` and `/auth/logout`. Never sent to other endpoints.
- Verified locally AND looked up in the `refresh_tokens` table (see §5.4) so we can revoke individual sessions. A refresh JWT whose `jti` is not in the table — or whose `revoked_at` is set — is rejected.

Rationale for HS256 over RS256: single-issuer / single-verifier service, no third party needs to verify our tokens, no advantage to asymmetric. Secret rotation is a future concern and is handled by supporting a `JWT_SECRET_PREVIOUS` env var for one rollover window.

### 5.3 Endpoints

All three live in `main.py`. None require `get_current_user` — they implement auth.

**`POST /auth/google`** — exchange Google access token for our session.

Request:
```json
{ "google_access_token": "ya29...." }
```
Backend:
1. Validates the Google token against `https://www.googleapis.com/oauth2/v3/userinfo` (same call `get_current_user` does today, lifted out).
2. Extracts `sub` and `email`. Rejects if either is missing.
3. Checks `AllowedUser` allowlist by email. Rejects with 403 if not allowed (same behaviour as today, but the check happens **once at login** instead of on every request).
4. Generates an access JWT and a refresh JWT. Persists the refresh JWT's `jti` in `refresh_tokens` with `user_sub`, `email`, `created_at`, `expires_at`, `revoked_at=null`, `user_agent` (from request header, truncated), `last_used_at`.
5. Returns:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 1800,
  "user": { "sub": "1234...", "email": "you@example.com" }
}
```

Rate limit: `5/minute` per IP (slowapi, same pattern as existing limited routes).

**`POST /auth/refresh`** — get a new access token using a refresh token.

Request:
```json
{ "refresh_token": "eyJ...." }
```
Backend:
1. Verifies signature, `exp`, `iss`, `aud`, `typ=="refresh"`. Rejects on any failure.
2. Looks up `jti` in `refresh_tokens`. Rejects if missing, if `revoked_at` is set, or if `expires_at` has passed.
3. **Rotates**: marks the current row as `revoked_at=now()`, inserts a new refresh row with a new `jti`, returns a new access JWT and a new refresh JWT.
4. Updates `last_used_at` on the old row before revoking (audit trail).

Rotation matters because it gives us **theft detection** for free: if the same refresh token is presented twice (a legitimate client and a stealer), the second use targets an already-revoked row and we can react (in v1: just reject; in a later version: cascade-revoke all of that user's tokens). The user does not need to be aware of rotation — it is transparent.

Rate limit: `30/minute` per IP.

**`POST /auth/logout`** — revoke current device's session.

Request:
```json
{ "refresh_token": "eyJ...." }
```
Backend: looks up the `jti`, sets `revoked_at=now()`. Returns `204`.

A future `POST /auth/logout-all` (out of scope for v1) would revoke every non-revoked row for a given `user_sub`.

### 5.4 Schema

One new table, created idempotently in `main.py`'s `lifespan` block following the same `CREATE TABLE IF NOT EXISTS` pattern as the existing tables there.

```sql
CREATE TABLE IF NOT EXISTS refresh_tokens (
    jti UUID PRIMARY KEY,
    user_sub TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS refresh_tokens_user_sub_idx
    ON refresh_tokens (user_sub) WHERE revoked_at IS NULL;
```

Matching SQLModel in `models.py`:

```python
class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    jti: UUID = Field(primary_key=True)
    user_sub: str = Field(index=True)
    email: str
    created_at: Optional[datetime] = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=func.now())
    )
    expires_at: datetime = Field(sa_column=Column(TIMESTAMP(timezone=True), nullable=False))
    last_used_at: Optional[datetime] = Field(sa_column=Column(TIMESTAMP(timezone=True)))
    revoked_at: Optional[datetime] = Field(sa_column=Column(TIMESTAMP(timezone=True)))
    user_agent: Optional[str] = None
```

No FK to a `users` table — we don't have one today, and `user_sub` is the same opaque string we use everywhere else. Adding a `users` table is a separate, larger refactor.

Cleanup: a periodic prune of `expires_at < now() - interval '30 days'` rows. v1 can defer this (table will accumulate at most a few hundred rows per pilot user); a simple `DELETE` run from an admin script (`Search Backend/`) is enough. Not a cron job in v1.

### 5.5 Backend changes — `get_current_user`

Replace the body of `get_current_user` (`main.py:187-249`) with local JWT verification:

```python
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    token = credentials.credentials

    # Dev fallback preserved — mock tokens starting with "user_" still pass.
    if token.startswith("user_"):
        return token

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience="api",
            issuer="smart-bookmark-manager",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject")
    return sub
```

Notes:
- No DB query on the hot path. The allowlist check moves to `/auth/google` and `/auth/refresh` (the latter re-checks on every refresh so removing someone from `AllowedUser` invalidates them within the next access-token lifetime, default 30 min).
- The `session: AsyncSession` parameter is dropped from `get_current_user`. Callers that used it as a side-effectful "give me a session too" pattern are not affected — every endpoint already takes its own `session` dep.
- The `Request` parameter is dropped (no longer needed for `app.state.http`).
- The Google `userinfo` call is **moved**, not deleted — it lives in the `/auth/google` handler now.

### 5.6 Library choice

Use **PyJWT** (`pyjwt==2.9.0` or current).

- Tiny, no transitive C deps, well-maintained.
- Already in the dependency graph of several existing libraries; adding it explicitly is a no-op at install size.
- Alternative considered: `python-jose`. Larger, supports JWE which we don't need, has had a maintenance gap. Rejected.

Add to `Search Backend/requirements.txt`:
```
pyjwt==2.9.0
```

### 5.7 Extension changes

Both extensions get the same logic; below is described once. Two places implement it (Chrome popup.js + Firefox popup.js) and `api.js` is shared in spirit (the file is duplicated per extension today, both must be updated).

**`api.js`** gains:
- `accessToken`, `refreshToken` in memory; persisted to `chrome.storage.local` as `accessToken` and `refreshToken`. The existing `authToken` key is **removed** during the migration shim (see §6).
- `_fetch` flow:
  1. If `accessToken` missing → throw "Not logged in" (caller shows login UI).
  2. Send request with `Authorization: Bearer ${accessToken}`.
  3. On 401: try `_refresh()` once. If it succeeds, retry the original request once. If `_refresh()` fails, clear tokens and throw a `"Session expired"` error that the caller can render as the login screen.
  4. Single-flight the refresh: if two parallel requests both hit 401, only one `/auth/refresh` call happens; the second awaits the first.
- `_refresh()`:
  - POSTs `{ refresh_token }` to `/auth/refresh`.
  - On success, updates both tokens in memory and in storage.
  - On any non-2xx, clears both tokens and rejects.

**`popup.js`** login handler:
- Same `launchWebAuthFlow` as today — gets a Google access token.
- Immediately POSTs it to `/auth/google`.
- Stores the returned `access_token` / `refresh_token`. **Does not** store the Google token.

**`popup.js`** logout handler:
- POSTs `refresh_token` to `/auth/logout` (best-effort — ignore errors).
- Clears both tokens from storage.

### 5.8 Why this satisfies the multi-device requirement

- Each device runs login independently and ends up with its own `(access_jwt, refresh_jwt)` pair, persisted to that device's `chrome.storage.local`. There is no shared session-id concept that a new login could overwrite.
- Refresh tokens are rotated per device. Device A refreshing its token does not touch device B's row in `refresh_tokens`. Device B's `jti` stays valid for the full 90-day window regardless of how often A refreshes.
- The only way device A can affect device B is an explicit "logout everywhere" call — which v1 does not expose.
- Token verification on the backend is stateless (signature + `exp`), so devices never serialize on a shared auth resource.

## 6. Migration & rollout

The change is **not** silently backwards-compatible — old Google access tokens stored under `authToken` will start failing the JWT decode in §5.5 immediately. The extension handles this gracefully:

1. On extension load, if `authToken` exists in storage but `accessToken` does not → delete `authToken` and force re-login. This runs **once**, in the `checkAuth()` paths (`Chrome Plugin/popup.js:checkAuth`, `Firefox Plugin/popup.js:checkAuth`, plus sidebar/manager equivalents that hydrate from storage).
2. From the user's perspective: one extra "Login with Google" click after updating the extension. After that, they stay logged in for ~90 days per device.

Backend rollout order matters slightly: deploy backend first (new endpoints + new `get_current_user`). At this point any extension still sending a Google access token will get 401 immediately. Then ship extension updates. Window of breakage = the time between the two deploys; for a pilot of ~one user, this is not worth a feature flag.

Optional safety net for the rollout window: keep the **old** `get_current_user` logic (Google userinfo call) reachable behind one env var `AUTH_ALLOW_LEGACY_GOOGLE_TOKEN=1`. If set, JWT decode failures fall through to the old Google check. Removed in the next release.

## 7. Configuration

New env vars (read in `main.py` startup or a thin `settings.py`):

| Var | Default | Notes |
|---|---|---|
| `JWT_SECRET` | (no default — required) | 32+ random bytes, base64 ok. Fail to start if missing in production. |
| `JWT_ACCESS_TTL_SECONDS` | `1800` | 30 min. |
| `JWT_REFRESH_TTL_SECONDS` | `7776000` | 90 days. |
| `JWT_ISSUER` | `smart-bookmark-manager` | |
| `JWT_AUDIENCE` | `api` | |
| `AUTH_ALLOW_LEGACY_GOOGLE_TOKEN` | `0` | One-release migration flag (§6). |

Railway: add `JWT_SECRET` as a sealed env var. Local dev: `.env` file (already in use for `OPENAI_API_KEY` etc.).

`Search Backend/verify_security.py` should be extended to fail-fast if `JWT_SECRET` is unset or shorter than 32 bytes.

## 8. Security considerations

- **Token storage in the extension**: `chrome.storage.local` is per-extension and not accessible to web pages, but is readable by any code running inside the extension. This is the same threat model as today, just with different tokens. XSS in our own extension UI would expose the refresh token; we already render bookmark titles/HTML so XSS hygiene matters either way — `setSafeHTML` is the relevant primitive.
- **Refresh token rotation**: gives us re-use detection (see §5.3). In v1 we just reject the duplicate; in a later version we cascade-revoke.
- **Signing-secret rotation**: support `JWT_SECRET_PREVIOUS` in §5.5 verify path. New tokens always signed with `JWT_SECRET`; verify tries current then previous. Out of v1 scope but the verify code should be structured to allow it without rewriting.
- **Allowlist enforcement timing**: removing someone from `AllowedUser` no longer kicks them instantly — they remain valid until their current access JWT expires (≤30 min) or they try to refresh. Acceptable for a pilot; if a faster kill switch is ever needed, expose `POST /admin/revoke-user/{sub}` that bulk-revokes their refresh rows.
- **Mock-auth fallback (`token.startswith("user_")`)**: preserved for local dev. Production deployments should refuse it. Add a check: if `os.getenv("ENVIRONMENT") == "production"`, do not honour the `user_` shortcut.
- **CORS**: unchanged — current setup is `allow_origins=["*"]` with `allow_credentials=False` (`main.py:172-178`). Tokens travel in the `Authorization` header, not cookies, so CSRF is not a concern.
- **HTTPS**: refresh tokens are long-lived bearer credentials; the deployed backend must be HTTPS-only. Already true on Railway. Local dev over plain HTTP is fine for the pilot.

## 9. Open questions

- **Should `/auth/google` also accept a Google ID token (JWT) in addition to an access token?** The extension currently asks for `openid email profile`, and OAuth implicit flow can return `id_token` if we add `response_type=id_token token` and a `nonce`. Validating an ID token locally (with Google's published keys) removes the userinfo round trip from `/auth/google` as well. Worth doing in a follow-up.
- **Device naming.** v1 stores `user_agent` only. If we add a "your active devices" screen later, we'll want a user-editable nickname column.
- **Sliding refresh vs fixed refresh.** Current design rotates `jti` on every refresh but resets the 90-day clock each time (sliding). Alternative: keep the original `created_at + 90 days` as the hard ceiling regardless of activity. Pick sliding for v1 — matches user intuition of "I use it, so I stay logged in".

## 10. Implementation phases

Suggested ordering. Each phase is independently testable.

**Phase 1 — Backend: JWT plumbing, no behaviour change.**
- Add `pyjwt` to `requirements.txt`.
- Add `JWT_SECRET` env handling (and the `verify_security.py` check).
- Create `auth.py` (new file) with `create_access_token`, `create_refresh_token`, `decode_token`, and the rotation helper. Pure functions, fully unit-testable.
- No endpoints, no `get_current_user` changes yet.

**Phase 2 — Backend: endpoints + table.**
- Add `RefreshToken` model in `models.py`.
- Add `refresh_tokens` table creation to `lifespan` in `main.py`.
- Add `POST /auth/google`, `POST /auth/refresh`, `POST /auth/logout` to `main.py`.
- `get_current_user` still does the old Google userinfo path. New endpoints work in parallel.

**Phase 3 — Backend: cut over `get_current_user`.**
- Replace `get_current_user` body with the JWT-verify version (§5.5).
- Keep `AUTH_ALLOW_LEGACY_GOOGLE_TOKEN=1` for one release (§6) so the extension can be updated separately.
- Deploy.

**Phase 4 — Extensions.**
- Update `Chrome Plugin/api.js` and `Firefox Plugin/api.js` with two-token storage, refresh-on-401, single-flight refresh.
- Update `popup.js` (both) to call `/auth/google` after the Google flow and store the returned tokens.
- Update `sidebar.js`, `manager.js`, and any other hydrators to read `accessToken` instead of `authToken`.
- Add the one-shot migration: delete legacy `authToken` and force re-login.
- Bump extension versions (`manifest.json` → `1.0.8`).

**Phase 5 — Cleanup.**
- Remove `AUTH_ALLOW_LEGACY_GOOGLE_TOKEN`. Remove the Google userinfo fallback in `get_current_user`.
- Add the refresh-token prune script.

Phases 1–3 are backend-only and can ship without an extension update. Phase 4 must follow Phase 3. Phase 5 follows after both stores have accepted the extension update.
