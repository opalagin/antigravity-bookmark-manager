const API_BASE_URL = 'http://localhost:8000';

const api = {
    async saveBookmark(url, title, content) {
        try {
            const response = await fetch(`${API_BASE_URL}/bookmarks`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: url,
                    title: title,
                    content_markdown: content || "" // Fallback for now
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to save bookmark');
            }

            return await response.json();
        } catch (error) {
            console.error("API Error (saveBookmark):", error);
            throw error;
        }
    },

    async searchBookmarks(query) {
        try {
            const response = await fetch(`${API_BASE_URL}/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query,
                    limit: 10
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to search bookmarks');
            }

            return await response.json();
        } catch (error) {
            console.error("API Error (searchBookmarks):", error);
            throw error;
        }
    },
    async chat(query) {
        try {
            const response = await fetch(`${API_BASE_URL}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to get chat response');
            }

            return await response.json();
        } catch (error) {
            console.error("API Error (chat):", error);
            throw error;
        }
    }
};

// Export for usage if using modules, but for simple extension logic, global 'api' is often used.
// We'll stick to global scope for simplicity in this non-module setup.
window.api = api;
