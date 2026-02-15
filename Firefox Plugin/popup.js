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

            // 2. Inject Extraction Scripts
            await browser.scripting.executeScript({
                target: { tabId: currentTab.id },
                files: ['lib/Readability.js', 'lib/turndown.js']
            });

            // 3. Execute Extraction Logic
            const executionResults = await browser.scripting.executeScript({
                target: { tabId: currentTab.id },
                files: ['extract.js']
            });

            const extractedData = executionResults[0].result;
            console.log("Extracted:", extractedData);

            // 3.5 Get Tags
            const tagsInput = document.getElementById('tags-input');
            const tags = tagsInput.value.split(',').map(t => t.trim()).filter(t => t);

            // 4. Send to Backend
            if (!window.api) throw new Error("API client not loaded");

            await window.api.saveBookmark(
                extractedData.url,
                extractedData.title,
                extractedData.content,
                tags
            );

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

            if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                document.body.innerHTML = `
                    <div class="result-container error">
                        <div class="icon">🚫</div>
                        <h3>Access Denied</h3>
                        <p>We are currently in <strong>Pilot Mode</strong>.</p>
                        <p>Your email is not on the allowed list.</p>
                        <button onclick="window.close()" class="primary-btn">Close</button>
                    </div>
                `;
                return;
            }

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

                if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                    bookmarksList.innerHTML = `
                        <li class="empty-state error-state">
                            <strong>Access Denied</strong><br>
                            You are not authorized to use the search in Pilot Mode.
                        </li>
                    `;
                } else {
                    bookmarksList.innerHTML = `<li class="empty-state">Error: ${error.message}</li>`;
                }
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

    // Initial state: Load recent bookmarks
    async function loadRecent() {
        try {
            bookmarksList.innerHTML = '<li class="empty-state">Loading recent...</li>';
            if (!window.api) throw new Error("API client not loaded");

            const recent = await window.api.getRecent(10);
            renderBookmarks(recent);

            if (recent.length === 0) {
                bookmarksList.innerHTML = '<li class="empty-state">No bookmarks saved yet.</li>';
            }
        } catch (error) {
            console.error("Recent fetch failed:", error);

            if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                bookmarksList.innerHTML = `
                    <li class="empty-state error-state">
                        <strong>Access Denied</strong><br>
                        You are not authorized to view bookmarks in Pilot Mode.
                    </li>
                `;
            } else {
                bookmarksList.innerHTML = `<li class="empty-state">Error: ${error.message}</li>`;
            }
        }
    }

    // Auth & Init
    async function checkAuth() {
        const stored = await browser.storage.local.get('authToken');
        if (stored.authToken) {
            api.setToken(stored.authToken);
            showLogoutButton();
            loadRecent();
        } else {
            showLogin();
        }
    }

    function showLogoutButton() {
        // Check if button already exists
        if (document.getElementById('logout-btn')) return;

        const header = document.querySelector('header');
        const logoutBtn = document.createElement('button');
        logoutBtn.id = 'logout-btn';
        logoutBtn.textContent = 'Logout';
        logoutBtn.className = 'secondary-btn'; // Assuming this class exists or will default to simple style
        logoutBtn.style.position = 'absolute';
        logoutBtn.style.right = '15px';
        logoutBtn.style.top = '15px';
        logoutBtn.style.fontSize = '0.8rem';
        logoutBtn.style.padding = '4px 8px';

        logoutBtn.addEventListener('click', async () => {
            await browser.storage.local.remove('authToken');
            api.setToken(null);
            document.getElementById('logout-btn').remove();
            showLogin();
        });

        header.appendChild(logoutBtn);
    }

    function showLogin() {
        // Clear Logout button if present
        const existingLogout = document.getElementById('logout-btn');
        if (existingLogout) existingLogout.remove();

        bookmarksList.innerHTML = `
            <div class="login-container">
                <p>Please login to save bookmarks.</p>
                <button id="login-btn" class="primary-btn" style="background-color: #4285F4;">Login with Google</button>
                <div style="font-size: 0.8em; margin-top: 10px; color: #666;">
                    Note: Requires configured Client ID
                </div>
            </div>
        `;

        document.getElementById('login-btn').addEventListener('click', async () => {
            try {
                bookmarksList.innerHTML = '<li class="empty-state">Authenticating...</li>';

                // CLIENT CONFIGURATION
                // TODO: User must replace this with their actual Client ID from Google Console
                const CLIENT_ID = "127114677197-aei7k7s99vosi3hpqqti1v8h3r493te8.apps.googleusercontent.com";
                const REDIRECT_URI = browser.identity.getRedirectURL();
                const AUTH_URL = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${CLIENT_ID}&response_type=token&redirect_uri=${encodeURIComponent(REDIRECT_URI)}&scope=openid%20email%20profile`;

                console.log("Launching Auth Flow:", AUTH_URL);

                const redirectUrl = await browser.identity.launchWebAuthFlow({
                    interactive: true,
                    url: AUTH_URL
                });

                if (redirectUrl) {
                    // Extract token from URL hash (access_token=...)
                    const url = new URL(redirectUrl);
                    const params = new URLSearchParams(url.hash.substring(1)); // hash starts with #
                    const token = params.get("access_token");

                    if (token) {
                        await browser.storage.local.set({ authToken: token });
                        api.setToken(token);
                        showLogoutButton();
                        bookmarksList.innerHTML = '<li class="empty-state">Logged in! Loading...</li>';
                        loadRecent();
                    } else {
                        throw new Error("No access token found in redirect.");
                    }
                }
            } catch (error) {
                console.error("Auth Failed:", error);
                bookmarksList.innerHTML = `
                    <li class="empty-state error-state">
                        Authentication Failed: ${error.message}<br>
                        <small>Check Client ID and Redirect URI in popup.js</small>
                    </li>
                `;
                // Re-show login button after a delay or let user retry
                setTimeout(showLogin, 5000);
            }
        });
    }

    checkAuth();
});
