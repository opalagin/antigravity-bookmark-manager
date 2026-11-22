# Antigravity Bookmark Manager

## Description
Bookmark manager with AI assistance. Saves bookmarks, supports tagging, and answers questions about bookmarks.

## Technologies
- PostgreSQL for storage
- Python's FastAPI as back-end
- Integration with OpenAI API
- Support for local LLMs
- Firefox extension
- Chrome extension

## Repo content

### `firefox-plugin`
Firefox plugin that allows users to save bookmarks and manage them with AI assistance.

### `chrome-plugin`
Chrome plugin that allows users to save bookmarks and manage them with AI assistance.

### `storage`
docker-compose to start the storage for local development.

### `search-backend`
Fast API back-end which provides actual functionality for browser extensions.

### `railway`
Railway configs that provides hosting and deployment for the bookmark manager.

### `docs`
Documentation for the bookmark manager.

## Tools
- uv
- ruff
- pyright
- docker
