# "Already Bookmarked" Indicator — Specification

Status: Draft
Date: 2026-11-18

## 1. Goal

Show at a glance that the page in the current tab is already saved:

1. **Toolbar icon** switches to a green variant on tabs whose URL is already bookmarked, and back to the default icon otherwise.
2. **Save button** in the popup turns green and reads **"Update Bookmark"** when the current page is already bookmarked.

Constraints:

- Keep it simple: no new UI elements, no new colors. Reuse the green the extension already uses for the "Saved!" flash (`.btn-success`, `#2ecc71 → #27ae60`).
- Do not send the user's browsing activity to the backend. `PRIVACY.md` §1.C promises *"does not monitor, log, or transmit your overall browsing activity"* and this feature must keep that true.
- Same behavior in Chrome/Edge and Firefox.

## 2. Non-goals

- **URL normalization** (`http` vs `https`, trailing slash, `#fragment`, `utm_*`). The match is exact, the same rule the backend already uses for upsert (`services.py:251`). Normalization is a separate feature because it changes how bookmarks are stored, not only how they are shown.
- Badges, text overlays or tooltips on the toolbar icon.
- Indicators inside the Manager page or Sidebar.
- A light theme or new design tokens beyond naming the existing green.

## 3. Current state (reference)

- **Upsert by exact URL.** `ingestion_service.process_bookmark` (`search-backend/services.py:241-263`) looks up `(user_id, url)` and overwrites `title`, `content_markdown` **and `tags`** if found. A unique constraint `unique_user_url (user_id, url)` backs this (`models.py:17`).
- **Saved URL** comes from `extract.js` → `window.location.href`, which equals `tab.url` for http(s) tabs (fragment included).
- **No lookup endpoint.** The closest is `GET /bookmarks?query=`, an `ILIKE` substring search on title/url (`services.py:554-558`). It is paginated and treats `%`/`_` as wildcards, so it is not usable for an exact check.
- **Background scripts** are empty placeholders in both plugins (`chrome-plugin/background.js`, `firefox-plugin/background.js`). Chrome uses an MV3 service worker; Firefox uses `background.scripts` (event page).
- **Permissions**: `activeTab, storage, scripting, identity` (+ `sidePanel` in Chrome). There is **no `tabs` permission**, so a background script cannot read `tab.url` for tabs the user has not interacted with.
- **Popup save button** (`popup.html:31`, `popup.js:15` `DEFAULT_SAVE_BTN_HTML`). `syncUIForState()` (`popup.js:59-84`) rewrites the button HTML on every state change. On success the button flashes `.btn-success` for 1.5 s (`popup.js:420-428`).
- **Tokens**: access/refresh JWTs live in `storage.local`. `/auth/refresh` **rotates** the refresh token and revokes the old one (`main.py:571`). If two contexts refresh at the same time, one of them ends up holding a revoked token.
- **Icons**: `icons/icon-{16,32,48,128}.png` show a violet→blue bookmark shape. `icons/icon.svg` is stale (older blue square) and does not match the PNGs.

## 4. Design

### 4.1 Approach: local URL set, synced from the backend (recommended)

| | A. Ask backend per tab (`/lookup?url=`) | B. Local set of bookmarked URLs |
|---|---|---|
| Sends visited URLs to the server | **Yes, on every tab switch/navigation** | No. Only the user's own bookmark URLs travel, and only server → device |
| Latency on tab switch | Network round-trip | Instant (in-memory `Set`) |
| Server load / rate limits | 1 call per navigation | 1 call per sync (~every 10 min or after a change) |
| Staleness | None | Up to the sync interval, but local changes are pushed immediately (§4.3) |
| Size | Tiny | ~100 B/URL, so 10k bookmarks ≈ 1 MB. Fine for a personal library |

**Pick B.** A would break the privacy promise and costs a request per navigation. B is simpler and works offline.

The popup also needs the existing bookmark's **tags** (§4.5). It already sends the open page's URL and content to `/tags/suggest` when it opens, so one extra exact lookup there adds no new disclosure.

### 4.2 Backend: two read-only endpoints

Both are scoped to `user_id` from the JWT and live next to `GET /bookmarks` in `main.py`.

#### `GET /bookmarks/urls`

Returns every URL the user has bookmarked. Used by the background script.

```json
{ "urls": ["https://example.com/a", "https://example.com/b"], "count": 2 }
```

- Query: `select(Bookmark.url).where(Bookmark.user_id == user_id)`. Selects one column and needs no new index; `unique_user_url` covers it.
- Rate limit: `30/minute`.
- **Route order:** register it before `/bookmarks/{bookmark_id}` routes. FastAPI only has PATCH/DELETE on that path today, but declaring it first avoids future collisions with a GET.

#### `GET /bookmarks/lookup?url=<url>`

Exact match for one URL. Used by the popup.

- `200` → `BookmarkResponse` (id, url, title, tags, created_at, updated_at; no `content_markdown`).
- `404` → `{"detail": "Not bookmarked"}`.
- `url` must be ≤ 2048 chars, the same bound as `TagSuggestRequest.url`, else `422`.
- Rate limit: `60/minute`.

Tests (add to a new `search-backend/test_bookmark_lookup.py`, same style as `test_auto_tagging.py`): owner sees own URLs; other users' URLs are not returned; exact match only (`…/a` ≠ `…/a/`); 404 path; 422 on overlong URL.

### 4.3 Background script: keep the set, paint the icon

Same file content for both browsers (`background.js`). It does **not** import `api.js`, to stay independent of the popup's token-refresh logic (see "Auth" below).

**State**

- `bookmarkedUrls: Set<string>` in memory, mirrored to `storage.local` as `bookmarkedUrls` (array) + `bookmarkedUrlsSyncedAt` (ms). This lets a restarted service worker or event page repaint immediately without a network call.

**Sync (`syncBookmarkedUrls()`)**

- Reads `apiUrl` + `accessToken` from `storage.local` and does `GET /bookmarks/urls` with `Authorization: Bearer …`.
- On `200`: replace the set, persist it, then `repaintAllTabs()`.
- On `401`/network error: keep the last known set and do nothing else. **Never call `/auth/refresh` from the background.** That avoids the rotation race described in §3. The next popup open refreshes the token, and the resulting `storage.onChanged` triggers a re-sync.
- Single-flight: if a sync is in progress, return the same promise.

**Sync triggers**

| Trigger | Action |
|---|---|
| `runtime.onStartup`, `runtime.onInstalled` | load from storage → repaint → sync |
| `storage.onChanged` on `accessToken` (login / token refresh) | sync |
| `storage.onChanged`: `accessToken` removed (logout) | clear set + storage keys → repaint (all default) |
| Message `{type: "bookmark-saved", url}` from popup | `set.add(url)`, persist, repaint tabs with that URL. No network |
| Message `{type: "bookmarks-changed"}` from Manager/Sidebar after delete/bulk delete | sync |
| Any tab event (below) when `Date.now() - syncedAt > 10 min` | sync in background (stale-while-revalidate) |

No `alarms` permission is needed; the staleness check on tab events is enough.

**Painting**

```js
const ICON_DEFAULT = { 16: "icons/icon-16.png", 32: "icons/icon-32.png", 48: "icons/icon-48.png", 128: "icons/icon-128.png" };
const ICON_SAVED   = { 16: "icons/icon-saved-16.png", 32: "icons/icon-saved-32.png", 48: "icons/icon-saved-48.png", 128: "icons/icon-saved-128.png" };

function paintTab(tab) {
  const saved = !!tab.url && bookmarkedUrls.has(tab.url);
  browser.action.setIcon({ tabId: tab.id, path: saved ? ICON_SAVED : ICON_DEFAULT });
  browser.action.setTitle({ tabId: tab.id, title: saved ? "Smart Bookmark Manager — saved" : "Smart Bookmark Manager" });
}
```

- Per-tab `setIcon` (with `tabId`) is used so each tab keeps its own state and switching tabs needs no extra work. Chrome and Firefox both reset per-tab icons on navigation, so the `onUpdated` handler repaints.
- Events: `tabs.onUpdated` (when `changeInfo.url` or `changeInfo.status === "complete"`), `tabs.onActivated` (fetch the tab via `tabs.get`), and `repaintAllTabs()` = `tabs.query({})` → `paintTab` each.
- Wrap `setIcon` in `try/catch`; tabs can close mid-call.
- The title change gives screen readers and colorblind users a non-color cue at no extra cost.

**Manifest changes**

- Both: add `"tabs"` to `permissions`. This is needed to read `tab.url` in the background. See risk R1.
- Firefox: `background.scripts` stays `["background.js"]`. The script uses `browser.*`, and the existing `globalThis.browser = globalThis.browser || chrome` shim covers Chrome.
- Bump `version` in both manifests.

### 4.4 Icon assets

- Add `icons/icon-saved-{16,32,48,128}.png` to both plugins. Use the **same bookmark silhouette** as the current PNGs, recolored to the existing success green gradient `#2ecc71 → #27ae60`. Keep the dot white so it reads on green.
- Produce them by recoloring the current PNGs, keeping the alpha channel and swapping the gradient, so the shape matches pixel for pixel. A tiny one-off Pillow script is enough; commit only the PNGs.
- While there, replace the stale `icons/icon.svg` with a source SVG that matches the PNGs, plus `icon-saved.svg`. This is optional but cheap.

### 4.5 Popup changes (`popup.js`, `popup.html`, `variables.css`)

**State.** Add one boolean next to the existing state machine (no new states):

```js
let isBookmarked = false;      // current tab URL already saved
let existingBookmark = null;   // BookmarkResponse from /bookmarks/lookup, or null
```

**API.** Add `api.lookupBookmark(url)` to `api.js` → `GET /bookmarks/lookup?url=${encodeURIComponent(url)}`. Return `null` on 404 instead of throwing. `_fetch` currently throws on any non-OK response, so handle 404 explicitly in this method.

**Flow in `prepareCurrentTab()`** (`popup.js:268`). Once `extractedData.url` is known, run `lookupBookmark()` **in parallel** with extraction/suggestions. Do not block on it; a failed lookup means "not bookmarked".

- If found: `isBookmarked = true`, `existingBookmark = result`.
  - **Seed chips with the existing tags** (`origin: 'user'`) and **skip the automatic `/tags/suggest` call**. The hint reads `"Saved tags"`. The user can still press ↻ Regenerate.
  - Why: re-saving overwrites `tags` (§3). Without this, opening the popup on a saved page and pressing the button would silently replace the user's curated tags with fresh AI suggestions.
- If the lookup resolves after suggestions have already populated chips, and the user has not edited anything (`!userEditedSinceRequest && removedKeys.size === 0`), replace the chips with the saved tags. Otherwise leave the user's edits alone and only flip the button color.

**Button rendering.** `syncUIForState()` picks the HTML and class from `isBookmarked`:

```js
const SAVED_SAVE_BTN_HTML =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg><span>Update Bookmark</span>';

setSafeHTML(saveBtn, isBookmarked ? SAVED_SAVE_BTN_HTML : DEFAULT_SAVE_BTN_HTML);
saveBtn.classList.toggle('btn-saved', isBookmarked);
saveBtn.title = isBookmarked ? 'This page is already in your library. Click to update it.' : '';
```

The filled bookmark glyph (`fill="currentColor"`) is the non-color cue inside the popup.

**After a successful save** (`popup.js:420`): set `isBookmarked = true`, then `browser.runtime.sendMessage({ type: 'bookmark-saved', url: extractedData.url })`. Ignore errors if the background is asleep. After the existing 1.5 s green flash the button settles into the green "Update Bookmark" state instead of going back to violet.

**CSS** (`variables.css`, both plugins). Name the existing green and reuse it:

```css
:root {
    --success: #27ae60;
    --success-hover: #2ecc71;
}

.btn.btn-saved {
    background: linear-gradient(180deg, var(--success-hover), var(--success));
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.18) inset, 0 6px 16px -8px var(--success);
}
```

Optionally point `.btn.btn-success` at the same variables. Do not change its `!important`s; the transient flash must still override `btn-saved`.

### 4.6 Manager / Sidebar

After any successful `deleteBookmark` / `bulkDelete` / "delete bookmarks with tag" in `manager.js` (and the sidebar, if it can delete), call `browser.runtime.sendMessage({ type: 'bookmarks-changed' })`. Edits (`PATCH`) cannot change a URL, so they need no message.

### 4.7 Docs

- `PRIVACY.md` §1: add that the extension keeps a **local copy of your bookmarked URLs** to show the saved indicator. The current tab's URL is compared **on the device** and is not sent to the backend. Update "Last Updated".
- `docs/frontend-design/README.md` color table: add `--success` / `--success-hover`.

## 5. Risks and open questions

- **R1 — `tabs` permission triggers a new install warning** ("Read your browsing history"). On update Chrome **disables the extension until the user accepts** the new permission, and AMO/CWS reviewers will ask why. Mitigation: justify it in the store listing as "used only to compare the current tab URL against your saved bookmarks, locally". Alternative considered: Chrome's `declarativeContent` + `SetIcon` avoids `tabs`, but it is Chrome-only, needs `ImageData` instead of paths, and adds a rule per URL. Rejected as not simple.
- **R2 — exact-match misses.** `https://x.com/a` vs `https://x.com/a/` vs `…/a#section` show as "not saved". This matches what the backend considers the same bookmark today. Fix it properly with a URL-normalization follow-up.
- **R3 — stale set across devices.** A bookmark saved from another browser shows up after ≤ 10 min, or on the next popup open/login. That is acceptable for an indicator.
- **R4 — large libraries.** The `/bookmarks/urls` payload grows linearly. If it becomes a problem, add `?since=<updated_at>` incremental sync or return SHA-256 hashes. Out of scope for v1.
- **Q1 — color choice.** This spec uses the existing success green for both icon and button. The alternative is a solid accent violet (`--accent`) for the saved state, but then the "Save" (violet gradient) and "Saved" button states are hard to tell apart. Green is recommended.

## 6. Implementation phases

1. **Backend**: `GET /bookmarks/urls`, `GET /bookmarks/lookup`, tests; `ruff` + `pyright` clean.
2. **Assets**: `icon-saved-*.png` for both plugins (plus refreshed SVG sources).
3. **Background**: sync + painting in `background.js`, `tabs` permission, version bump. Identical code in both plugins.
4. **Popup**: `lookupBookmark`, `isBookmarked`, saved-tags seeding, `btn-saved` CSS, `bookmark-saved` message. Identical code in both plugins.
5. **Manager/Sidebar**: `bookmarks-changed` messages.
6. **Docs**: `PRIVACY.md`, design README tokens.

## 7. Manual test plan (both browsers)

1. Logged out → every tab shows the default icon; popup button violet "Save Current Page".
2. Log in on a saved page → within a moment the icon turns green; popup shows green "Update Bookmark" with the existing tags as chips and no auto-suggest.
3. Save a new page → green flash → button stays green; icon turns green immediately in that tab and any other tab on the same URL.
4. Switch between a saved and an unsaved tab → icon follows instantly, with no network request (check DevTools → background → Network).
5. Delete the bookmark in Manager → icon on that tab returns to default.
6. Navigate within a saved tab to an unsaved URL (including SPA `pushState`) → icon resets.
7. Restart the browser offline → saved tabs still show green (from `storage.local`).
8. Let the access token expire, then switch tabs → no logout and no refresh request from the background; icon keeps last known state; opening the popup refreshes and re-syncs.
9. Log out → all icons return to default; `bookmarkedUrls` is removed from storage.
