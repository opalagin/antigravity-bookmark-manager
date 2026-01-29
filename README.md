# Smart Bookmark Manager

An AI-powered personal knowledge base that allows you to "chat with your reading list." This system consists of a Firefox Extension for saving/searching and a Python Backend for storage and retrieval.

## 🌟 Current Functionality

*   **Firefox Extension**:
    *   **Popup UI**: Clean, modern interface for quick actions.
    *   **Save Page**: Instantly save the current browser tab (URL & Title) to your local database.
    *   **Search**: Search your bookmarks using natural language queries.
*   **Backend & Storage**:
    *   **FastAPI Service**: Handles ingestion and vector search requests.
    *   **PostgreSQL + pgvector**: Stores bookmark metadata and vector embeddings for semantic search.

## ⚠️ Limitations (v1.0)

*   **Content Extraction**: Currently saves semantic metadata (Title/URL) but does not yet perform full-text extraction of the webpage body.
*   **AI Generation**: The "Search" feature currently returns raw matching bookmarks based on vector similarity or keywords, but does not yet generate a synthesized AI answer (RAG chat).
*   **Localhost Only**: The extension is hardcoded to communicate with `http://localhost:8000`.
*   **No Authentication**: Single-user system designed for local use.

## 🚀 How to Launch

### 1. Start the Database
Ensure you have **Docker Desktop** installed and running.

```bash
cd Storage
docker-compose up -d
```
This spins up a PostgreSQL container with the `pgvector` extension on port `5432`.

### 2. Start the Backend API
Ensure you have **Python 3.10+** installed.

```bash
cd "Search Backend"

# Recommended: Create a virtual environment
# python -m venv venv
# source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload
```
The API will be available at `http://localhost:8000`.

### 3. Load the Firefox Extension
1.  Open Firefox and navigate to `about:debugging`.
2.  Select **"This Firefox"** from the sidebar.
3.  Click **"Load Temporary Add-on..."**.
4.  Navigate to the `Firefox Plugin/` folder in this project.
5.  Select the `manifest.json` file.

The extensions icon (🔖) should appear in your toolbar. Click it to start saving and searching!
