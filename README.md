# Smart Bookmark Manager

An AI-powered personal knowledge base that allows you to "chat with your reading list." This system consists of a Firefox Extension for saving/searching and a Python Backend for storage and retrieval.

## 🌟 Key Features

*   **Firefox Extension**:
    *   **Popup UI**: Clean interface for saving, searching, and managing bookmarks.
    *   **Smart Fallback**: Captures article text using `Readability.js` even on complex sites.
    *   **Tagging Support**: Organizes bookmarks with custom tags during save.
    *   **Authentication**: Secure OAuth2 login via Google (Firefox Identity API).
*   **Backend & Storage**:
    *   **Multi-Tenancy**: Data is isolated per user.
    *   **FastAPI Service**: Handles ingestion, vector search, and RAG chat.
    *   **PostgreSQL + pgvector**: Stores bookmark metadata and vector embeddings.
    *   **AI Integration**: Connected to OpenAI (`gpt-4o-mini`) for generating answers.

## ⚠️ Configuration Required

Before running, you **must** configure the following:

1.  **Google OAuth2 Client ID**:
    - Create a Web Application credential in Google Cloud Console.
    - Add the redirect URI provided by the extension (check console logs).
    - Update `CLIENT_ID` in `Firefox Plugin/popup.js`.
2.  **OpenAI API Key**:
    - Set `OPENAI_API_KEY` environment variable for the backend.

## 🚀 How to Launch

### 1. Start the Database
Ensure you have **Docker Desktop** installed and running.

```bash
cd Storage
docker-compose up -d
```
This spins up a PostgreSQL container with the `pgvector` extension on port `5432`.

**IMPORTANT**: If you have an old database volume, you must reset it to apply the new schema (Multi-tenancy & Tags).
- Run `python reset_db.py` in `Search Backend/` (if enabled)
- OR: `docker-compose down -v` and then `up -d` to start fresh.

### 2. Start the Backend API
Ensure you have **Python 3.10+** installed.

```bash
cd "Search Backend"

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate  # Windows
# source .venv/bin/activate # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set OpenAI API Key (Required for Chat Generation)
$env:OPENAI_API_KEY="sk-your-key-here"

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


The extension icon (🔖) should appear in your toolbar.
- **Click the Icon** to Save the current page.
- **Open Sidebar (Ctrl+B)** and select "Smart Bookmarks" to chat with your library.
