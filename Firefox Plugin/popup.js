document.addEventListener('DOMContentLoaded', () => {
    const saveBtn = document.getElementById('save-btn');
    const searchInput = document.getElementById('search-input');
    const bookmarksList = document.getElementById('bookmarks-list');

    // 1. Handle Save Button Click
    saveBtn.addEventListener('click', async () => {
        try {
            // Loading state
            saveBtn.disabled = true;
            const originalText = saveBtn.innerHTML;
            saveBtn.innerHTML = '<span class="icon">⏳</span> Saving...';

            // Get current tab
            const tabs = await browser.tabs.query({ active: true, currentWindow: true });
            const currentTab = tabs[0];

            if (!currentTab) {
                throw new Error("No active tab found");
            }

            // Call API
            // Note: Content extraction to be implemented. sending title as content placeholder for now.
            // Using a simple fallback object if window.api is missing for some reason
            if (!window.api) throw new Error("API client not loaded");

            await window.api.saveBookmark(currentTab.url, currentTab.title, `[Content of ${currentTab.title}]`);

            // Success feedback
            saveBtn.innerHTML = '<span class="icon">✅</span> Saved!';
            saveBtn.style.backgroundColor = '#00b894';

            setTimeout(() => {
                saveBtn.innerHTML = originalText;
                saveBtn.style.backgroundColor = '';
                saveBtn.disabled = false;
            }, 1500);

        } catch (error) {
            console.error("Save failed:", error);
            saveBtn.innerHTML = '<span class="icon">❌</span> Error';
            saveBtn.title = error.message;
            saveBtn.style.backgroundColor = '#d63031';

            setTimeout(() => {
                saveBtn.innerHTML = originalText; // Reset to original text "Save Current Page"
                if (originalText.includes('Saved')) { // Safety check if text was stale
                    saveBtn.innerHTML = '<span class="icon">🔖</span> Save Current Page';
                }
                saveBtn.title = '';
                saveBtn.style.backgroundColor = '';
                saveBtn.disabled = false;
            }, 2000);
        }
    });

    // 2. Handle Search Input
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value;

        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            if (!query.trim()) {
                bookmarksList.innerHTML = '<li class="empty-state">Start typing to search...</li>';
                return;
            }

            try {
                bookmarksList.innerHTML = '<li class="empty-state">Searching...</li>';
                if (!window.api) throw new Error("API client not loaded");

                const results = await window.api.searchBookmarks(query);
                renderBookmarks(results);
            } catch (error) {
                console.error("Search failed:", error);
                bookmarksList.innerHTML = `<li class="empty-state">Error: ${error.message}</li>`;
            }
        }, 300); // 300ms debounce
    });

    // 3. Render Helpers
    function renderBookmarks(bookmarks) {
        bookmarksList.innerHTML = '';
        if (bookmarks.length === 0) {
            bookmarksList.innerHTML = '<li class="empty-state">No results found</li>';
            return;
        }

        bookmarks.forEach(bookmark => {
            const li = document.createElement('li');
            li.textContent = bookmark.title || bookmark.url;
            li.title = bookmark.url;
            li.addEventListener('click', () => {
                browser.tabs.create({ url: bookmark.url });
            });
            bookmarksList.appendChild(li);
        });
    }

    // Initial state
    bookmarksList.innerHTML = '<li class="empty-state">Ready to search</li>';
});
