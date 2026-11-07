globalThis.browser = globalThis.browser || (typeof chrome !== 'undefined' ? chrome : null);
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
    },

    async getConfig() {
        try {
            const result = await browser.storage.local.get("apiUrl");
            const baseUrl = result.apiUrl || "http://localhost";
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 2000);
            try {
                const response = await fetch(`${baseUrl}/config`, {
                    method: 'GET',
                    signal: controller.signal
                });
                if (response.ok) {
                    return await response.json();
                }
            } finally {
                clearTimeout(timer);
            }
        } catch (_e) {
            // Fall through to default config
        }
        return { tag_suggest_timeout_ms: 4000 };
    },

    async suggestTags(url, title, contentMarkdown, options = {}) {
        return this._fetch('/tags/suggest', {
            method: 'POST',
            body: JSON.stringify({
                url,
                title,
                content_markdown: contentMarkdown || ""
            }),
            ...options
        });
    }
};

const TagUtils = {
    tagKey(s) {
        if (typeof s !== 'string') return '';
        const norm = s
            .normalize('NFKC')
            .replace(/ß/g, 'ss')
            .replace(/ẞ/g, 'ss')
            .toLowerCase()
            .trim()
            .replace(/[\s_]+/g, '-')
            .replace(/^[-/]+|[-/]+$/g, '');
        if (!norm) return '';
        return norm
            .split(/\/+/)
            .map(seg => seg.replace(/-+/g, '-').replace(/^-+|-+$/g, ''))
            .filter(Boolean)
            .join('/');
    },

    mergeSuggestionIntoChips(currentChips, suggestionResponse, userEdited, removedKeys = new Set()) {
        if (
            !suggestionResponse ||
            suggestionResponse.source === 'fallback' ||
            !Array.isArray(suggestionResponse.tags)
        ) {
            return {
                chips: currentChips.map(c => ({ ...c })),
                fallback: true
            };
        }

        const newSet = new Set(Array.isArray(suggestionResponse.new_tags) ? suggestionResponse.new_tags : []);
        const reusedSet = new Set(Array.isArray(suggestionResponse.reused_existing) ? suggestionResponse.reused_existing : []);
        const isTagNew = (t) => {
            if (newSet.has(t)) return true;
            if (reusedSet.has(t)) return false;
            return false;
        };

        const canReplace =
            !userEdited &&
            removedKeys.size === 0 &&
            currentChips.every(c => c.origin === 'suggested');

        if (canReplace) {
            const nextChips = [];
            const seen = new Set();
            for (const t of suggestionResponse.tags) {
                const k = this.tagKey(t);
                if (!k || seen.has(k) || removedKeys.has(k)) continue;
                seen.add(k);
                nextChips.push({
                    tag: t,
                    origin: 'suggested',
                    isNew: isTagNew(t)
                });
            }
            return { chips: nextChips, fallback: false };
        }

        const nextChips = currentChips.map(c => ({ ...c }));
        const existingKeys = new Set(nextChips.map(c => this.tagKey(c.tag)));
        for (const t of suggestionResponse.tags) {
            const k = this.tagKey(t);
            if (!k || existingKeys.has(k) || removedKeys.has(k)) continue;
            existingKeys.add(k);
            nextChips.push({
                tag: t,
                origin: 'suggested',
                isNew: isTagNew(t)
            });
        }
        return { chips: nextChips, fallback: false };
    },

    filterTagAutocomplete(vocabTags, rawQuery, excludedTags = [], limit = 8) {
        const q = (rawQuery || '').trim();
        const qKey = this.tagKey(q) || q.toLowerCase();
        if (!qKey) return [];

        const excludedKeys = new Set((excludedTags || []).map(t => this.tagKey(t)));
        const items = (vocabTags || [])
            .map(entry => (typeof entry === 'string' ? { tag: entry, count: 1 } : entry))
            .filter(entry => entry && typeof entry.tag === 'string' && entry.tag.trim().length > 0);

        const matches = [];
        for (const entry of items) {
            const k = this.tagKey(entry.tag);
            if (!k || excludedKeys.has(k)) continue;
            const lowerTag = entry.tag.toLowerCase();
            const isPrefix = lowerTag.startsWith(q.toLowerCase()) || k.startsWith(qKey);
            const isSub = isPrefix || lowerTag.includes(q.toLowerCase()) || k.includes(qKey);
            if (isSub) {
                matches.push({
                    tag: entry.tag,
                    count: Number(entry.count) || 0,
                    isPrefix
                });
            }
        }

        matches.sort((a, b) => {
            if (a.isPrefix !== b.isPrefix) return a.isPrefix ? -1 : 1;
            if (b.count !== a.count) return b.count - a.count;
            return a.tag.localeCompare(b.tag);
        });

        return matches.slice(0, limit).map(m => m.tag);
    },

    attachTagAutocomplete(inputEl, options = {}) {
        if (!inputEl || typeof document === 'undefined') return null;
        const {
            getVocabTags = () => [],
            getExcludedTags = () => [],
            getQuery = (val) => val,
            onSelect = () => {},
            dropdownParent = inputEl.parentElement
        } = options;

        const dropdown = document.createElement('ul');
        dropdown.className = 'tag-autocomplete-menu hidden';
        if (dropdownParent) {
            const pos = typeof window !== 'undefined' && window.getComputedStyle
                ? window.getComputedStyle(dropdownParent).position
                : '';
            if (!pos || pos === 'static') {
                dropdownParent.style.position = 'relative';
            }
            dropdownParent.appendChild(dropdown);
        }

        let activeIndex = -1;
        let currentItems = [];

        const hide = () => {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
            activeIndex = -1;
            currentItems = [];
        };

        const render = () => {
            if (inputEl.disabled || inputEl.readOnly) {
                hide();
                return;
            }
            const query = getQuery(inputEl.value);
            const matches = this.filterTagAutocomplete(
                getVocabTags(),
                query,
                getExcludedTags()
            );
            currentItems = matches;
            if (matches.length === 0) {
                hide();
                return;
            }
            activeIndex = 0;
            dropdown.innerHTML = '';
            matches.forEach((tag, idx) => {
                const li = document.createElement('li');
                li.className = `tag-autocomplete-item${idx === activeIndex ? ' active' : ''}`;
                li.textContent = tag;
                li.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    onSelect(tag);
                    hide();
                });
                dropdown.appendChild(li);
            });
            dropdown.classList.remove('hidden');
        };

        const updateHighlight = () => {
            const children = dropdown.querySelectorAll('.tag-autocomplete-item');
            children.forEach((el, idx) => {
                el.classList.toggle('active', idx === activeIndex);
            });
        };

        inputEl.addEventListener('input', () => {
            render();
        });

        inputEl.addEventListener('keydown', (e) => {
            if (dropdown.classList.contains('hidden') || currentItems.length === 0) {
                return;
            }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIndex = (activeIndex + 1) % currentItems.length;
                updateHighlight();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIndex = (activeIndex - 1 + currentItems.length) % currentItems.length;
                updateHighlight();
            } else if (e.key === 'Tab' && activeIndex >= 0 && currentItems[activeIndex]) {
                e.preventDefault();
                onSelect(currentItems[activeIndex]);
                hide();
            } else if (e.key === 'Escape') {
                hide();
            }
        });

        inputEl.addEventListener('blur', () => {
            setTimeout(hide, 120);
        });

        return {
            hide,
            render,
            isOpen: () => !dropdown.classList.contains('hidden') && currentItems.length > 0,
            getSelected: () => (activeIndex >= 0 ? currentItems[activeIndex] : null)
        };
    }
};

// Export for usage if using modules, but for simple extension logic, global 'api' is often used.
// We'll stick to global scope for simplicity in this non-module setup.
globalThis.api = api;
globalThis.TagUtils = TagUtils;
if (typeof window !== 'undefined') {
    window.api = api;
    window.TagUtils = TagUtils;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { api, TagUtils };
}
