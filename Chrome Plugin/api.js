// API Base URL is now dynamic via chrome.storage.local

const api = {
    token: null,

    setToken(token) {
        this.token = token;
    },

    getToken() {
        return this.token;
    },

    async _fetch(endpoint, options = {}) {
        if (!this.token) {
            throw new Error("No Auth Token. Please login.");
        }

        // Get Base URL from storage or default
        const result = await chrome.storage.local.get("apiUrl");
        const baseUrl = result.apiUrl || "http://localhost";

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.token}`,
            ...options.headers
        };

        const response = await fetch(`${baseUrl}${endpoint}`, {
            ...options,
            headers: headers
        });

        if (!response.ok) {
            if (response.status === 401) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || "Unauthorized");
            }
            if (response.status === 403) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || "Pilot Mode Access Denied");
            }
            const errorData = await response.json();
            throw new Error(errorData.detail || 'API Request Failed');
        }

        return await response.json();
    },

    async saveBookmark(url, title, content, tags = []) {
        return this._fetch('/bookmarks', {
            method: 'POST',
            body: JSON.stringify({
                url: url,
                title: title,
                content_markdown: content || "",
                tags: tags
            })
        });
    },

    async searchBookmarks(query) {
        return this._fetch('/search', {
            method: 'POST',
            body: JSON.stringify({
                query: query,
                limit: 10
            })
        });
    },
    async chat(query) {
        return this._fetch('/chat', {
            method: 'POST',
            body: JSON.stringify({
                query: query
            })
        });
    },

    async getRecent(limit = 10) {
        return this._fetch(`/recent?limit=${limit}`, {
            method: 'GET'
        });
    }
};

// Export for usage if using modules, but for simple extension logic, global 'api' is often used.
// We'll stick to global scope for simplicity in this non-module setup.
window.api = api;
