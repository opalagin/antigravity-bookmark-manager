document.addEventListener('DOMContentLoaded', () => {
    const saveBtn = document.getElementById('save-btn');
    const searchInput = document.getElementById('search-input');
    const bookmarksList = document.getElementById('bookmarks-list');

    // Helper for safe HTML setting
    function setSafeHTML(element, html) {
        element.innerHTML = ""; // Clear
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        while (doc.body.firstChild) {
            element.appendChild(doc.body.firstChild);
        }
    }

    // 1. Handle Save Button Click
    saveBtn.addEventListener('click', async () => {
        try {
            // Loading state
            saveBtn.disabled = true;
            const originalText = saveBtn.textContent;
            // saveBtn.innerHTML = '<span class="icon">⏳</span> Saving...';
            setSafeHTML(saveBtn, '<span class="icon">⏳</span> Saving...');

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

            // 4. Send to Backend
            if (!window.api) throw new Error("API client not loaded");

            await window.api.saveBookmark(
                extractedData.url,
                extractedData.title,
                extractedData.content,
                [] // Removed tags
            );

            // Success feedback
            // saveBtn.innerHTML = '<span class="icon">✅</span> Saved!';
            setSafeHTML(saveBtn, '<span class="icon">✅</span> Saved!');
            saveBtn.style.backgroundColor = '#00b894';

            setTimeout(() => {
                // saveBtn.innerHTML = originalText;
                saveBtn.textContent = originalText;
                saveBtn.style.backgroundColor = '';
                saveBtn.disabled = false;
            }, 1500);

        } catch (error) {
            console.error("Save failed:", error);

            if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                // document.body.innerHTML = ...
                const errorContainer = `
                    <div class="result-container error">
                        <div class="icon">🚫</div>
                        <h3>Access Denied</h3>
                        <p>We are currently in <strong>Pilot Mode</strong>.</p>
                        <p>Your email is not on the allowed list.</p>
                        <button id="close-btn" class="primary-btn">Close</button>
                    </div>
                `;
                setSafeHTML(document.body, errorContainer);
                document.getElementById('close-btn').onclick = () => window.close();
                return;
            }

            // saveBtn.innerHTML = '<span class="icon">❌</span> Error';
            setSafeHTML(saveBtn, '<span class="icon">❌</span> Error');
            saveBtn.title = error.message;
            saveBtn.style.backgroundColor = '#d63031';

            setTimeout(() => {
                // saveBtn.innerHTML = originalText; // Reset to original text "Save Current Page"
                saveBtn.textContent = originalText;
                if (originalText.includes('Saved')) { // Safety check if text was stale
                    setSafeHTML(saveBtn, '<span class="icon">🔖</span> Save Current Page');
                }
                saveBtn.title = '';
                saveBtn.style.backgroundColor = '';
                saveBtn.disabled = false;
            }, 2000);
        }
    });

    // 1.5 Handle Manage Library
    const manageBtn = document.getElementById('manage-btn');
    if (manageBtn) {
        manageBtn.addEventListener('click', () => {
            browser.tabs.create({ url: browser.runtime.getURL("manager.html") });
        });
    }

    // 1.6 Handle Settings Dropdown and Reembed
    const settingsBtn = document.getElementById('settings-btn');
    const settingsDropdown = document.getElementById('settings-dropdown');
    const reembedBtn = document.getElementById('reembed-btn');

    if (settingsBtn && settingsDropdown) {
        settingsBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // Prevent document click from immediately closing it
            settingsDropdown.classList.toggle('hidden');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!settingsDropdown.contains(e.target) && e.target !== settingsBtn) {
                settingsDropdown.classList.add('hidden');
            }
        });
    }

    if (reembedBtn) {
        reembedBtn.addEventListener('click', async () => {
            if (!window.api) return;
            try {
                reembedBtn.disabled = true;
                reembedBtn.textContent = 'Starting re-embed...';
                
                await window.api.startReembed();
                
                // Start polling
                const pollInterval = setInterval(async () => {
                    try {
                        const status = await window.api.getReembedStatus();
                        if (!status || status.status === "none" || status.status === "starting") {
                            reembedBtn.textContent = 'Starting...';
                        } else if (status.status === "running") {
                            const percent = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
                            reembedBtn.textContent = `Re-embedding... (${percent}%)`;
                        } else if (status.status === "completed") {
                            clearInterval(pollInterval);
                            reembedBtn.textContent = 'Completed!';
                            setTimeout(() => {
                                reembedBtn.disabled = false;
                                reembedBtn.textContent = 'Reembed your bookmarks...';
                                settingsDropdown.classList.add('hidden');
                            }, 2000);
                        } else if (status.status === "failed") {
                            clearInterval(pollInterval);
                            reembedBtn.textContent = 'Failed!';
                            console.error("Re-embed failed:", status.error);
                            setTimeout(() => {
                                reembedBtn.disabled = false;
                                reembedBtn.textContent = 'Reembed your bookmarks...';
                            }, 3000);
                        }
                    } catch (pollErr) {
                        console.error("Polling error:", pollErr);
                    }
                }, 1500);

            } catch (err) {
                console.error("Failed to start re-embed:", err);
                reembedBtn.textContent = 'Error starting';
                setTimeout(() => {
                    reembedBtn.disabled = false;
                    reembedBtn.textContent = 'Reembed your bookmarks...';
                }, 2000);
            }
        });
    }

    // 2. Handle Search Input
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value;

        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            if (!query.trim()) {
                // bookmarksList.innerHTML = '<li class="empty-state">Start typing to search...</li>';
                setSafeHTML(bookmarksList, '<li class="empty-state">Start typing to search...</li>');
                return;
            }

            try {
                // bookmarksList.innerHTML = '<li class="empty-state">Searching...</li>';
                setSafeHTML(bookmarksList, '<li class="empty-state">Searching...</li>');
                if (!window.api) throw new Error("API client not loaded");

                const results = await window.api.searchBookmarks(query);
                renderBookmarks(results);
            } catch (error) {
                console.error("Search failed:", error);

                if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                    setSafeHTML(bookmarksList, `
                        <li class="empty-state error-state">
                            <strong>Access Denied</strong><br>
                            You are not authorized to use the search in Pilot Mode.
                        </li>
                    `);
                } else {
                    setSafeHTML(bookmarksList, `<li class="empty-state">Error: ${error.message}</li>`);
                }
            }
        }, 300); // 300ms debounce
    });

    // 3. Render Helpers
    function renderBookmarks(bookmarks) {
        bookmarksList.innerHTML = '';
        if (bookmarks.length === 0) {
            setSafeHTML(bookmarksList, '<li class="empty-state">No results found</li>');
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
            setSafeHTML(bookmarksList, '<li class="empty-state">Loading recent...</li>');
            if (!window.api) throw new Error("API client not loaded");

            const recent = await window.api.getRecent(10);
            renderBookmarks(recent);

            if (recent.length === 0) {
                setSafeHTML(bookmarksList, '<li class="empty-state">No bookmarks saved yet.</li>');
            }
        } catch (error) {
            console.error("Recent fetch failed:", error);

            if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                setSafeHTML(bookmarksList, `
                    <li class="empty-state error-state">
                        <strong>Access Denied</strong><br>
                        You are not authorized to view bookmarks in Pilot Mode.
                    </li>
                `);
            } else {
                setSafeHTML(bookmarksList, `<li class="empty-state">Error: ${error.message}</li>`);
            }
        }
    }

    // Auth & Init
    async function checkAuth() {
        // One-shot migration shim: if legacy 'authToken' exists but 'accessToken' does not, remove it to force re-login
        const storedAuth = await browser.storage.local.get('authToken');
        const storedJwt = await browser.storage.local.get(['accessToken', 'refreshToken']);
        if (storedAuth.authToken && !storedJwt.accessToken) {
            await browser.storage.local.remove('authToken');
        }

        if (storedJwt.accessToken && storedJwt.refreshToken) {
            api.setTokens(storedJwt.accessToken, storedJwt.refreshToken);
            showLogoutButton();
            loadRecent();
        } else {
            showLogin();
        }
    }

    function showLogoutButton() {
        // Check if button already exists
        if (document.getElementById('logout-btn')) return;

        const container = document.getElementById('logout-container');
        if (!container) return;
        
        const logoutBtn = document.createElement('button');
        logoutBtn.id = 'logout-btn';
        logoutBtn.title = 'Logout';
        logoutBtn.innerHTML = '🚪';
        logoutBtn.className = 'icon-btn'; 

        logoutBtn.addEventListener('click', async () => {
            const stored = await browser.storage.local.get('refreshToken');
            const rt = stored.refreshToken;
            if (rt) {
                // Best-effort logout hit to backend
                try {
                    const result = await browser.storage.local.get("apiUrl");
                    const baseUrl = result.apiUrl || "http://localhost";
                    await fetch(`${baseUrl}/auth/logout`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ refresh_token: rt })
                    });
                } catch (e) {
                    console.error("Logout request to backend failed:", e);
                }
            }
            await api.clearTokens();
            document.getElementById('logout-btn').remove();
            showLogin();
        });

        container.appendChild(logoutBtn);
    }

    function showLogin() {
        // Clear Logout button if present
        const existingLogout = document.getElementById('logout-btn');
        if (existingLogout) existingLogout.remove();

        setSafeHTML(bookmarksList, `
            <div class="login-container">
                <p>Please login to save bookmarks.</p>
                <button id="login-btn" class="primary-btn" style="background-color: #4285F4;">Login with Google</button>
                <div style="font-size: 0.8em; margin-top: 10px; color: #666;">
                    Note: Requires configured Client ID
                </div>
            </div>
        `);

        document.getElementById('login-btn').addEventListener('click', async () => {
            try {
                setSafeHTML(bookmarksList, '<li class="empty-state">Authenticating...</li>');

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
                        setSafeHTML(bookmarksList, '<li class="empty-state">Exchanging token with backend...</li>');
                        const result = await browser.storage.local.get("apiUrl");
                        const baseUrl = result.apiUrl || "http://localhost";
                        
                        const exchangeResponse = await fetch(`${baseUrl}/auth/google`, {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify({ google_access_token: token })
                        });
                        
                        if (!exchangeResponse.ok) {
                            const errorData = await exchangeResponse.json().catch(() => ({}));
                            throw new Error(errorData.detail || "Backend authentication failed");
                        }
                        
                        const data = await exchangeResponse.json();
                        await browser.storage.local.set({
                            accessToken: data.access_token,
                            refreshToken: data.refresh_token
                        });
                        api.setTokens(data.access_token, data.refresh_token);
                        
                        showLogoutButton();
                        setSafeHTML(bookmarksList, '<li class="empty-state">Logged in! Loading...</li>');
                        loadRecent();
                    } else {
                        throw new Error("No access token found in redirect.");
                    }
                }
            } catch (error) {
                console.error("Auth Failed:", error);
                setSafeHTML(bookmarksList, `
                    <li class="empty-state error-state">
                        Authentication Failed: ${error.message}<br>
                        <small>Check Client ID and Redirect URI in popup.js</small>
                    </li>
                `);
                // Re-show login button after a delay or let user retry
                setTimeout(showLogin, 5000);
            }
        });
    }

    checkAuth();
});
