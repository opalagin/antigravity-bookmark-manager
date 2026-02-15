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
    *   UI Entry Points: Browser Action (Popup) for quick save/search, Side Panel for persistent chat.
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
*   **Transport**: HTTPS only for all endpoints.
*   **Persistence**: Database storage persisted to Docker volumes.

### 3.4 Security Refinements (Pilot Phase)
*   **Pilot Mode**: Access restricted to an allowlist of users.
*   **User Identification**: Users identified via Email (provider: Google).
*   **Access Control**:
    *   Check authenticated user's email against `allowed_users` table.
    *   If not allowed, reject with 403 Forbidden and "Pilot Mode" message.
*   **Rate Limiting**: Implement API Rate Limiting (e.g., via `slowapi`) to prevent abuse.

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
    *   **User Profile / Logout**.

### 5.2 Sidebar / Full Page UI (Deep Interaction)
*   **Chat Mode**:
    *   Full conversational interface (User vs AI).
    *   History of previous queries (optional).
    *   Rich text rendering for AI answers (Markdown support in extension).

## 6. Future Scope
*   **Local LLM**: Run small model inside browser or locally to reduce API costs.
*   **Cross-Browser**: Port to Chrome/Edge.
