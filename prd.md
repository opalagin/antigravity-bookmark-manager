# Product Requirements Document (PRD): Smart Bookmark Manager

## 1. Executive Summary
**Project Name:** Smart Bookmark Manager
**Goal:** Create an AI-powered personal knowledge base that allows users to bookmark web pages and later retrieve information via natural language chat using RAG (Retrieval-Augmented Generation).
**Core Value Proposition:** "Chat with your reading list."
**Key Constraint:** The entire user interface (saving and searching) must live within the Firefox Extension. No separate web application.

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
    *   Search/RAG: LangChain or direct implementation.
*   **Storage**:
    *   Primary DB: **PostgreSQL**
    *   Vector Extension: **pgvector**.
    *   Search: Hybrid (BM25 + Vector).

## 3. Functional Requirements

### 3.1 Ingestion Flow (Bookmark)
*   **User Action**: Click extension icon -> Click "Save Page".
*   **System Action**:
    1.  Extension extracts content (Readability).
    2.  Converts to Markdown.
    3.  Sends payload to Backend API.
    4.  Backend processes (clean, chunk, embed, store).
    5.  Extension shows success notification.

### 3.2 Retrieval Flow (Search/Chat)
*   **User Action**: Open Extension Popup or Sidebar -> Type question (e.g., "Do I have articles about X?").
*   **System Action**:
    1.  Extension sends query to Backend API.
    2.  Backend performs Vector + Keyword search in `pgvector`.
    3.  Retrieves context chunks.
    4.  Generates answer via LLM.
    5.  Streams response to the Extension UI with citations.

## 4. Data Model (PostgreSQL)

### `bookmarks`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | Primary Key |
| `url` | TEXT | Unique URL |
| `title` | TEXT | Page Title |
| `content_markdown` | TEXT | Archival content |
| `created_at` | TIMESTAMPTZ | Timestamp |

### `bookmark_embeddings`
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | Primary Key |
| `bookmark_id` | UUID | FK to `bookmarks` |
| `chunk_index` | INT | Sequence number |
| `chunk_text` | TEXT | Context text |
| `embedding` | VECTOR(1536) | Vector data |

## 5. Interface Design (Firefox Extension)

### 5.1 Popup UI (Quick Actions)
*   **Main View**:
    *   "Save Current Page" Big Button.
    *   Simple Search Bar ("Ask your bookmarks...").
    *   Recent Bookmarks list (compact).

### 5.2 Sidebar / Full Page UI (Deep Interaction)
*   **Chat Mode**:
    *   Full conversational interface (User vs AI).
    *   History of previous queries (optional).
    *   Rich text rendering for AI answers (Markdown support in extension).

## 6. Future Scope
*   **Local LLM**: Run small model inside browser or locally to reduce API costs.
*   **Cross-Browser**: Port to Chrome/Edge.
