# Smart Bookmark Manager

An AI-powered personal knowledge base that allows you to "chat with your reading list." This system consists of a Firefox Extension for saving/searching and a Python Backend for storage and retrieval.

## 🌟 Current Functionality

*   **Firefox Extension**:
    *   **Popup UI**: Clean, modern interface for quick actions.
    *   **Sidebar Chat**: Persistent "Smart Bookmarks" sidebar for chatting with your knowledge base.
    *   **Full Content Extraction**: Automatically captures article text using `Readability.js` (with `Turndown` for Markdown conversion), ensuring high-quality context for the AI.
    *   **Smart Fallback**: Even on JavaScript-heavy sites, the extension captures page text.
*   **Backend & Storage**:
    *   **FastAPI Service**: Handles ingestion, vector search, and RAG chat.
    *   **PostgreSQL + pgvector**: Stores bookmark metadata and vector embeddings for semantic search.
    *   **AI Integration**: Connected to OpenAI (`gpt-4o-mini`) for generating synthesized answers based on your bookmarks.

## ⚠️ Limitations (v1.1)

*   **Localhost Only**: The extension is currently configured to communicate with `http://localhost:8000`.
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

# Set OpenAI API Key (Required for Chat Generation)
# Windows (PowerShell):
$env:OPENAI_API_KEY="sk-your-key-here"
# Mac/Linux:
export OPENAI_API_KEY=sk-your-key-here

# Run the server
uvicorn main:app --reload
```
The API will be available at `http://localhost:8000`.

**Note**: If you do not provide an `OPENAI_API_KEY`, the backend will run in **Mock Mode**, returning raw search chunks instead of a generated answer.

### 3. Load the Firefox Extension
1.  Open Firefox and navigate to `about:debugging`.
2.  Select **"This Firefox"** from the sidebar.
3.  Click **"Load Temporary Add-on..."**.
4.  Navigate to the `Firefox Plugin/` folder in this project.
5.  Select the `manifest.json` file.

The extension icon (🔖) should appear in your toolbar.
- **Click the Icon** to Save the current page.
- **Open Sidebar (Ctrl+B)** and select "Smart Bookmarks" to chat with your library.
