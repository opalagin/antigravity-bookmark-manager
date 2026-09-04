globalThis.browser = globalThis.browser || chrome;
// API Base URL is now dynamic via browser.storage.local

const api = {
    accessToken: null,
    refreshToken: null,
    refreshPromise: null, // to single-flight the refresh

    setTokens(accessToken, refreshToken) {
        this.accessToken = accessToken;
        this.refreshToken = refreshToken;
    },

    getAccessToken() {
        return this.accessToken;
    },

    getRefreshToken() {
        return this.refreshToken;
    },

    async _fetch(endpoint, options = {}) {
        if (!this.accessToken) {
            throw new Error("No Auth Token. Please login.");
        }

        // Get Base URL from storage or default
        const result = await browser.storage.local.get("apiUrl");
        const baseUrl = result.apiUrl || "http://localhost";

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.accessToken}`,
            ...options.headers
        };

        let response = await fetch(`${baseUrl}${endpoint}`, {
            ...options,
            headers: headers
        });

        if (response.status === 401) {
            // Try refreshing the token (single-flighted)
            try {
                await this._refresh();
                // Retry once with the new access token
                const newHeaders = {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.accessToken}`,
                    ...options.headers
                };
                response = await fetch(`${baseUrl}${endpoint}`, {
                    ...options,
                    headers: newHeaders
                });
            } catch (refreshError) {
                // If refresh fails, clear everything and propagate "Session expired"
                await this.clearTokens();
                throw new Error("Session expired. Please login again.");
            }
        }

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

    async _refresh() {
        if (this.refreshPromise) {
            return this.refreshPromise;
        }

        this.refreshPromise = (async () => {
            if (!this.refreshToken) {
                throw new Error("No refresh token available");
            }

            const result = await browser.storage.local.get("apiUrl");
            const baseUrl = result.apiUrl || "http://localhost";

            const response = await fetch(`${baseUrl}/auth/refresh`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ refresh_token: this.refreshToken })
            });

            if (!response.ok) {
                throw new Error("Token refresh request failed");
            }

            const data = await response.json();
            this.setTokens(data.access_token, data.refresh_token);
            await browser.storage.local.set({
                accessToken: data.access_token,
                refreshToken: data.refresh_token
            });
        })();

        try {
            await this.refreshPromise;
        } finally {
            this.refreshPromise = null;
        }
    },

    async clearTokens() {
        this.accessToken = null;
        this.refreshToken = null;
        await browser.storage.local.remove(["accessToken", "refreshToken", "authToken"]);
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
    },

    async getAllBookmarks(skip = 0, limit = 50, tagPrefix = null, query = null) {
        let url = `/bookmarks?skip=${skip}&limit=${limit}`;
        if (tagPrefix) url += `&tag_prefix=${encodeURIComponent(tagPrefix)}`;
        if (query) url += `&query=${encodeURIComponent(query)}`;
        return this._fetch(url, { method: 'GET' });
    },

    async getTags() {
        return this._fetch('/tags', { method: 'GET' });
    },

    async updateBookmark(id, data) {
        return this._fetch(`/bookmarks/${id}`, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    },

    async deleteBookmark(id) {
        return this._fetch(`/bookmarks/${id}`, { method: 'DELETE' });
    },

    async bulkUpdateTags(oldPrefix, newPrefix) {
        return this._fetch('/bookmarks/bulk_update_tags', {
            method: 'POST',
            body: JSON.stringify({ old_prefix: oldPrefix, new_prefix: newPrefix })
        });
    },

    async bulkDelete(ids) {
        return this._fetch('/bookmarks/bulk_delete', {
            method: 'POST',
            body: JSON.stringify({ bookmark_ids: ids })
        });
    },

    async bulkAddTag(ids, tag) {
        return this._fetch('/bookmarks/bulk_add_tag', {
            method: 'POST',
            body: JSON.stringify({ bookmark_ids: ids, tag: tag })
        });
    },

    async bulkRemoveTag(ids, tag) {
        return this._fetch('/bookmarks/bulk_remove_tag', {
            method: 'POST',
            body: JSON.stringify({ bookmark_ids: ids, tag: tag })
        });
    },

    async startReembed() {
        return this._fetch('/bookmarks/reembed', {
            method: 'POST'
        });
    },

    async getReembedStatus() {
        return this._fetch('/bookmarks/reembed/status', {
            method: 'GET'
        });
    }
};

// Export for usage if using modules, but for simple extension logic, global 'api' is often used.
// We'll stick to global scope for simplicity in this non-module setup.
window.api = api;
