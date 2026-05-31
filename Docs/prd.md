# Product Requirements Document (PRD): Smart Bookmark Manager

## 1. Executive Summary
**Project Name:** Smart Bookmark Manager
**Goal:** Create a secure, multi-user AI-powered personal knowledge base that allows users to bookmark, tag, and later retrieve information via natural language chat using RAG.
**Core Value Proposition:** "Chat with your reading list."
**Key Constraint:** The entire user interface must live within the Firefox Extension. The backend must be containerized and support multi-tenancy.

## 2. System Architecture

### High-Level Components
1.  **Firefox Extension**: The sole user interface. Handles capturing content and provides the chat/search UI (Popup or Sidebar).
2.  **Backend API**: Headless service for ingestion, search, and AI orchestration.
3.  **Database**: Persistent storage for content and vector embeddings (Postgres + pgvector).
4.  **AI Engine**: LLM integration for generation and Embedding model for retrieval.

### Technology Stack
*   **Frontend / Extension**:
    *   Browser: Firefox (Manifest V3)
    *   Language: JavaScript/HTML/CSS (React or standard JS)
    *   UI Entry Points: Browser Action (Popup) for quick save/search, Side Panel for persistent chat, Full-page Manager Tab for library curation.
    *   Key Libraries: `Readability.js` (Content extraction), `Turndown` (HTML to Markdown).
*   **Backend**:
    *   Language: Python
    *   Framework: FastAPI (Async, high performance).
    *   Authentication: OAuth2 + PKCE (via Firefox Identity).
    *   Search/RAG: LangChain or direct implementation.
*   **Storage**:
    *   Primary DB: **PostgreSQL** (Persistent via Docker Volumes).
    *   Vector Extension: **pgvector**.
    *   Search: Hybrid (BM25 + Vector).
*   **Infrastructure**:
    *   Containerization: Docker & Docker Compose.
    *   Proxy: Nginx (Termination & HTTPS).

## 3. Functional Requirements

### 3.1 Ingestion Flow (Bookmark)
*   **User Action**: Click extension icon -> Login (if needed) -> Click "Save Page".
*   **System Action**:
    1.  Extension extracts content (Readability).
    2.  Suggests tags (optional AI pre-fetch).
    3.  User confirms/edits tags.
    4.  Sends payload (content + tags + auth token) to Backend API.
    5.  Backend validates token and tenancy.
    6.  Backend processes (clean, chunk, embed, store).
    7.  Extension shows success notification.

### 3.2 Retrieval Flow (Search/Chat)
*   **User Action**: Open Extension Popup -> Type question.
*   **System Action**:
    1.  Extension sends query + auth token to Backend API.
    2.  Backend authenticates and restricts search to user's data.
    3.  Backend performs Vector + Keyword search.
    4.  Generates answer via LLM.
    5.  Streams response.

### 3.3 Security & Multi-tenancy
*   **Authentication**: OAuth2 via Firefox Identity API.
*   **Authorization**: Backend validates JWT/opaque tokens. Data access strictly scoped to `user_id`.
*   **Mutation Authorization**: PATCH and DELETE endpoints must verify the target bookmark's `user_id` matches the authenticated user before applying the change. Return 404 (not 403) on mismatch to avoid existence leaks.
*   **Transport**: HTTPS only for all endpoints.
*   **Persistence**: Database storage persisted to Docker volumes.

### 3.4 Security Refinements (Pilot Phase)
*   **Pilot Mode**: Access restricted to an allowlist of users.
*   **User Identification**: Users identified via Email (provider: Google).
*   **Access Control**:
    *   Check authenticated user's email against `allowed_users` table.
    *   If not allowed, reject with 403 Forbidden and "Pilot Mode" message.
*   **Rate Limiting**: Implement API Rate Limiting (e.g., via `slowapi`) to prevent abuse.

### 3.5 Management Flow (Curate Library)
*   **User Action**: Open Popup -> click "Manage Library" -> Manager Tab opens in a new browser tab.
*   **System Action**:
    1.  Manager fetches a paginated bookmark list (with optional tag-prefix and free-text filters) and the user's tag tree.
    2.  User can rename a bookmark's title, edit its tags, delete a bookmark, or bulk-select multiple bookmarks to delete or re-tag.
    3.  "Organize into hierarchy" is performed by editing tags. Dragging a bookmark onto a tag-tree node adds or replaces the corresponding slash-path tag (e.g. dropping onto `work/projects` sets the tag to `work/projects`).
    4.  Renaming a tag-tree node performs a server-side bulk update: every bookmark whose tag starts with the old prefix gets the prefix rewritten.
    5.  Deleting a tag-tree node either (a) removes that tag from all matching bookmarks or (b) deletes all matching bookmarks. The user explicitly confirms which.
    6.  All mutations are scoped to the authenticated `user_id`. Backend cascade-deletes embeddings via the existing `bookmark_embeddings.bookmark_id ON DELETE CASCADE` foreign key.

## 4. Data Model (PostgreSQL)

### `bookmarks`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | Primary Key |
| `user_id` | TEXT | Owner ID (Auth Subject) |
| `url` | TEXT | Unique URL (Per user) |
| `title` | TEXT | Page Title |
| `content_markdown` | TEXT | Archival content |
| `tags` | TEXT[] | Array of tags |
| `created_at` | TIMESTAMPTZ | Timestamp |
| `updated_at` | TIMESTAMPTZ | Last mutation timestamp (for sort/audit in Manager) |

> **Tag convention**: Tags are stored as a flat string array but interpreted as hierarchical paths using `/` as a separator (e.g. `work/projects/auth`). The Manager UI reconstructs the tag tree client-side. No schema change is needed to support hierarchy.

### `bookmark_embeddings`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | Primary Key |
| `bookmark_id` | UUID | FK to `bookmarks` |
| `chunk_index` | INT | Sequence number |
| `chunk_text` | TEXT | Context text |
| `embedding` | VECTOR(1536) | Vector data |

### `allowed_users`
| Column | Type | Description |
| :--- | :--- | :--- |
| `email` | TEXT | Primary Key, Allowed User Email |
| `created_at` | TIMESTAMPTZ | Timestamp |

## 5. Interface Design (Firefox Extension)

### 5.1 Popup UI (Quick Actions)
*   **Main View**:
    *   "Save Current Page" with **Tag Input**.
    *   Simple Search Bar ("Ask your bookmarks...").
    *   Recent Bookmarks list.
    *   **"Manage Library" button** that opens the full-page Manager Tab.
    *   **User Profile / Logout**.

### 5.2 Sidebar / Full Page UI (Deep Interaction)
*   **Chat Mode**:
    *   Full conversational interface (User vs AI).
    *   History of previous queries (optional).
    *   Rich text rendering for AI answers (Markdown support in extension).

### 5.3 Manager UI (Full-Page Tab)
A dedicated `manager.html` opened in a new browser tab via `browser.tabs.create`. Three-pane layout:

*   **Left Pane — Tag Tree**:
    *   Collapsible tree built from slash-separated tag paths (e.g. `work/projects/auth`).
    *   Each node shows the count of bookmarks tagged at or under it.
    *   Includes virtual nodes: "All bookmarks" (root) and "Untagged".
    *   Per-node actions: rename (triggers server-side bulk prefix-rewrite) and delete (with confirm dialog choosing between "remove tag from bookmarks" or "delete bookmarks").
*   **Center Pane — Bookmark Table**:
    *   Columns: title, URL, tags, created_at, updated_at.
    *   Sortable, free-text filterable, multi-selectable via checkboxes.
    *   Pagination or infinite scroll.
    *   Selecting the active tag-tree node filters the table to that prefix.
*   **Right Pane — Detail / Edit**:
    *   Editable title (rename).
    *   Editable tag chips with autocomplete from the user's existing tags.
    *   Source URL (read-only, click to open).
    *   Archived markdown preview (read-only).
    *   Delete button (confirm dialog).
*   **Bulk Actions Toolbar** (visible when one or more rows selected): Delete, Add Tag, Remove Tag, Move to Tag (replaces a tag prefix).
*   **Drag-and-Drop**: Dragging selected bookmarks onto a tag-tree node assigns that tag.
*   **Empty / Error States**: Friendly empty state for new users; inline toasts for save/delete success and errors.

## 6. Future Scope
*   **Local LLM**: Run small model inside browser or locally to reduce API costs.
*   **Cross-Browser**: Port to Chrome/Edge.
*   **Drag-to-Reorder Tag Tree**: Persist user-defined ordering of tag-tree nodes (currently alphabetical).
*   **Saved Views / Smart Filters**: Persisted Manager filters (e.g. "untagged from this month", "no tags + over 30 days old").
