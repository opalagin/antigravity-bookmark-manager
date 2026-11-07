globalThis.browser = globalThis.browser || (typeof chrome !== 'undefined' ? chrome : null);

function initPopup() {
    const saveBtn = document.getElementById('save-btn');
    const searchInput = document.getElementById('search-input');
    const bookmarksList = document.getElementById('bookmarks-list');
    const tagsSection = document.getElementById('tags-section');
    const tagsStatusHint = document.getElementById('tags-status-hint');
    const retryExtractBtn = document.getElementById('retry-extract-btn');
    const regenerateTagsBtn = document.getElementById('regenerate-tags-btn');
    const chipsBox = document.getElementById('chips-box');
    const chipsList = document.getElementById('chips-list');
    const tagInput = document.getElementById('tag-input');

    const DEFAULT_SAVE_BTN_HTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg><span>Save Current Page</span>';

    // State machine (§5.8):
    // idle | extracting | extract_failed | suggesting | ready | submitting | saved | save_failed
    let popupState = 'idle';
    let extractedData = null; // { url, title, content }
    let chips = []; // [{ tag: string, origin: 'suggested' | 'user', isNew: boolean }]
    let removedKeys = new Set();
    let userEditedSinceRequest = false;
    let currentRequestId = 0;
    let suggestAbortController = null;
    let suggestTimeoutTimer = null;
    let suggestTimeoutMs = 4000;
    let vocabTags = [];
    let autocompleteCtrl = null;
    let regenCooldownTimer = null;
    let regenInCooldown = false;

    const tagUtils = globalThis.TagUtils || (typeof window !== 'undefined' && window.TagUtils);

    function setSafeHTML(element, html) {
        if (!element) return;
        element.innerHTML = "";
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        while (doc.body.firstChild) {
            element.appendChild(doc.body.firstChild);
        }
    }

    function setPopupState(nextState, hintText = null) {
        popupState = nextState;
        if (hintText !== null && tagsStatusHint) {
            tagsStatusHint.textContent = hintText;
        }
        syncUIForState();
    }

    function isEditableState() {
        return popupState === 'suggesting' || popupState === 'ready';
    }

    function syncUIForState() {
        const canSave = popupState === 'suggesting' || popupState === 'ready';
        if (saveBtn && popupState !== 'submitting' && popupState !== 'saved' && popupState !== 'save_failed') {
            saveBtn.disabled = !canSave;
            setSafeHTML(saveBtn, DEFAULT_SAVE_BTN_HTML);
        }

        if (retryExtractBtn) {
            retryExtractBtn.classList.toggle('hidden', popupState !== 'extract_failed');
            retryExtractBtn.disabled = popupState !== 'extract_failed';
        }

        if (regenerateTagsBtn) {
            regenerateTagsBtn.classList.toggle('hidden', popupState === 'extract_failed');
            const allowRegen = (popupState === 'suggesting' || popupState === 'ready') && !regenInCooldown;
            regenerateTagsBtn.disabled = !allowRegen;
        }

        if (tagInput) {
            const inputEditable = isEditableState();
            tagInput.disabled = !inputEditable;
            tagInput.readOnly = !inputEditable;
        }

        renderChips();
    }

    function renderChips() {
        if (!chipsList) return;
        chipsList.innerHTML = '';
        const editable = isEditableState();

        chips.forEach((chip, index) => {
            const span = document.createElement('span');
            const isNewStyle = chip.origin === 'suggested' && chip.isNew;
            span.className = `popup-tag-chip${isNewStyle ? ' new-tag' : ' reused-tag'}`;
            span.dataset.tag = chip.tag;
            span.dataset.origin = chip.origin;
            if (isNewStyle) {
                span.title = 'New tag suggestion';
            }

            const labelNode = document.createTextNode(chip.tag);
            span.appendChild(labelNode);

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'chip-remove';
            removeBtn.textContent = '×';
            removeBtn.title = `Remove ${chip.tag}`;
            removeBtn.disabled = !editable;
            removeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                removeChipAt(index);
            });

            span.appendChild(removeBtn);
            chipsList.appendChild(span);
        });
    }

    function removeChipAt(index) {
        if (!isEditableState()) return;
        const [removed] = chips.splice(index, 1);
        if (removed && tagUtils) {
            const k = tagUtils.tagKey(removed.tag);
            if (k) removedKeys.add(k);
        }
        userEditedSinceRequest = true;
        renderChips();
    }

    function addUserChip(rawTag) {
        if (!isEditableState()) return false;
        const cleaned = (rawTag || '').trim().replace(/^,+|,+$/g, '').trim();
        if (!cleaned) return false;
        const k = tagUtils ? tagUtils.tagKey(cleaned) : cleaned.toLowerCase();
        if (!k) return false;

        // If the user explicitly re-adds a tag they previously removed, un-ban it
        removedKeys.delete(k);
        userEditedSinceRequest = true;

        const exists = chips.some(c => (tagUtils ? tagUtils.tagKey(c.tag) : c.tag.toLowerCase()) === k);
        if (!exists) {
            chips.push({ tag: cleaned, origin: 'user', isNew: false });
            renderChips();
        }
        return true;
    }

    function abortInFlightSuggest() {
        if (suggestTimeoutTimer) {
            clearTimeout(suggestTimeoutTimer);
            suggestTimeoutTimer = null;
        }
        if (suggestAbortController) {
            try {
                suggestAbortController.abort();
            } catch (_e) {
                // ignore
            }
            suggestAbortController = null;
        }
    }

    async function loadServerConfigAndVocab() {
        if (!window.api) return;
        try {
            const cfg = await window.api.getConfig();
            if (cfg && typeof cfg.tag_suggest_timeout_ms === 'number' && cfg.tag_suggest_timeout_ms > 0) {
                suggestTimeoutMs = cfg.tag_suggest_timeout_ms;
            }
        } catch (_e) {
            suggestTimeoutMs = 4000;
        }

        try {
            const tags = await window.api.getTags();
            if (Array.isArray(tags)) {
                vocabTags = tags;
            }
        } catch (_e) {
            vocabTags = [];
        }
    }

    async function requestSuggestions() {
        if (!extractedData || !window.api) return;
        abortInFlightSuggest();

        currentRequestId += 1;
        const reqId = currentRequestId;
        userEditedSinceRequest = false;

        const controller = new AbortController();
        suggestAbortController = controller;

        setPopupState('suggesting', 'Suggesting…');

        let timedOut = false;
        suggestTimeoutTimer = setTimeout(() => {
            timedOut = true;
            try {
                controller.abort();
            } catch (_e) {
                // ignore
            }
        }, suggestTimeoutMs);

        try {
            const response = await window.api.suggestTags(
                extractedData.url,
                extractedData.title,
                extractedData.content,
                { signal: controller.signal }
            );

            if (reqId !== currentRequestId || popupState === 'submitting' || popupState === 'saved') {
                return;
            }

            if (suggestTimeoutTimer) {
                clearTimeout(suggestTimeoutTimer);
                suggestTimeoutTimer = null;
            }

            const hasTypedText = Boolean(tagInput && tagInput.value.trim().length > 0);
            const hasUserEdit =
                userEditedSinceRequest ||
                hasTypedText ||
                removedKeys.size > 0 ||
                chips.some(c => c.origin === 'user');

            const merged = tagUtils
                ? tagUtils.mergeSuggestionIntoChips(chips, response, hasUserEdit, removedKeys)
                : { chips, fallback: true };

            chips = merged.chips;

            if (merged.fallback || (chips.length === 0 && (!response.tags || response.tags.length === 0))) {
                setPopupState('ready', 'No suggestions; add tags manually');
            } else {
                setPopupState('ready', 'Suggested tags');
            }
        } catch (_err) {
            if (reqId !== currentRequestId || popupState === 'submitting' || popupState === 'saved') {
                return;
            }
            if (suggestTimeoutTimer) {
                clearTimeout(suggestTimeoutTimer);
                suggestTimeoutTimer = null;
            }
            const _reason = timedOut ? 'timeout' : 'error';
            setPopupState('ready', 'No suggestions; add tags manually');
        }
    }

    async function prepareCurrentTab() {
        if (tagsSection) {
            tagsSection.classList.remove('hidden');
        }
        extractedData = null;
        setPopupState('extracting', 'Extracting page…');

        try {
            const tabs = await browser.tabs.query({ active: true, currentWindow: true });
            const currentTab = tabs && tabs[0];

            if (!currentTab || !currentTab.id || !currentTab.url || !/^https?:\/\//i.test(currentTab.url)) {
                throw new Error('Unsupported tab URL for extraction');
            }

            await browser.scripting.executeScript({
                target: { tabId: currentTab.id },
                files: ['lib/Readability.js', 'lib/turndown.js']
            });

            const executionResults = await browser.scripting.executeScript({
                target: { tabId: currentTab.id },
                files: ['extract.js']
            });

            const result = executionResults && executionResults[0] && executionResults[0].result;
            if (!result || !result.url) {
                throw new Error('Extraction returned empty data');
            }

            extractedData = {
                url: result.url,
                title: result.title || '',
                content: result.content || ''
            };

            // Start suggesting immediately; Save is enabled in 'suggesting'
            await requestSuggestions();
        } catch (err) {
            console.warn('Extraction failed:', err);
            extractedData = null;
            setPopupState('extract_failed', 'Could not extract page; click Retry');
        }
    }

    // Wire chip input events
    if (tagInput) {
        if (tagUtils && chipsBox) {
            autocompleteCtrl = tagUtils.attachTagAutocomplete(tagInput, {
                dropdownParent: chipsBox,
                getVocabTags: () => vocabTags,
                getExcludedTags: () => chips.map(c => c.tag),
                getQuery: (val) => val,
                onSelect: (selectedTag) => {
                    addUserChip(selectedTag);
                    tagInput.value = '';
                    tagInput.focus();
                }
            });
        }

        tagInput.addEventListener('input', () => {
            userEditedSinceRequest = true;
            if (tagInput.value.includes(',')) {
                const parts = tagInput.value.split(',');
                const last = parts.pop();
                parts.forEach(part => addUserChip(part));
                tagInput.value = last || '';
            }
        });

        tagInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                if (
                    e.key === 'Enter' &&
                    autocompleteCtrl &&
                    autocompleteCtrl.isOpen() &&
                    autocompleteCtrl.getSelected()
                ) {
                    addUserChip(autocompleteCtrl.getSelected());
                    tagInput.value = '';
                    autocompleteCtrl.hide();
                    return;
                }
                if (tagInput.value.trim()) {
                    addUserChip(tagInput.value);
                    tagInput.value = '';
                    if (autocompleteCtrl) autocompleteCtrl.hide();
                }
            } else if (e.key === 'Backspace' && tagInput.value === '' && chips.length > 0) {
                removeChipAt(chips.length - 1);
            }
        });
    }

    if (chipsBox && tagInput) {
        chipsBox.addEventListener('click', () => {
            if (!tagInput.disabled) {
                tagInput.focus();
            }
        });
    }

    if (retryExtractBtn) {
        retryExtractBtn.addEventListener('click', () => {
            if (popupState === 'extract_failed') {
                prepareCurrentTab();
            }
        });
    }

    if (regenerateTagsBtn) {
        regenerateTagsBtn.addEventListener('click', () => {
            if (popupState !== 'suggesting' && popupState !== 'ready') return;
            if (regenInCooldown) return;

            // Start 5s cooldown when regenerating from 'ready' (or when superseding an in-flight request)
            const wasInFlight = popupState === 'suggesting';
            if (!wasInFlight) {
                regenInCooldown = true;
                if (regenCooldownTimer) clearTimeout(regenCooldownTimer);
                regenCooldownTimer = setTimeout(() => {
                    regenInCooldown = false;
                    syncUIForState();
                }, 5000);
            }
            requestSuggestions();
        });
    }

    // 1. Handle Save Button Click (§5.8 Rule 5)
    saveBtn.addEventListener('click', async () => {
        if (popupState !== 'suggesting' && popupState !== 'ready') return;
        if (!extractedData) return;

        // Snapshot tags at click time and freeze editor
        const snapshotTags = chips.map(c => c.tag);
        currentRequestId += 1;
        abortInFlightSuggest();
        if (autocompleteCtrl) autocompleteCtrl.hide();

        setPopupState('submitting');
        saveBtn.disabled = true;
        setSafeHTML(saveBtn, '<span class="icon">⏳</span> Saving...');

        try {
            if (!window.api) throw new Error("API client not loaded");

            await window.api.saveBookmark(
                extractedData.url,
                extractedData.title,
                extractedData.content,
                snapshotTags
            );

            setPopupState('saved', 'Saved!');
            setSafeHTML(saveBtn, '<span class="icon">✅</span> Saved!');
            saveBtn.classList.add('btn-success');
            loadRecent();

            setTimeout(() => {
                saveBtn.classList.remove('btn-success');
                setPopupState('ready');
            }, 1500);
        } catch (error) {
            console.error("Save failed:", error);

            if (error.message.includes("Pilot Mode") || error.message.includes("Access Denied")) {
                const errorContainer = `
                    <div class="login-container error">
                        <div class="icon">🚫</div>
                        <h3>Access Denied</h3>
                        <p>We are currently in <strong>Pilot Mode</strong>.</p>
                        <p>Your email is not on the allowed list.</p>
                        <button id="close-btn" class="btn">Close</button>
                    </div>
                `;
                setSafeHTML(document.body, errorContainer);
                document.getElementById('close-btn').onclick = () => window.close();
                return;
            }

            setPopupState('save_failed');
            setSafeHTML(saveBtn, '<span class="icon">❌</span> Error');
            saveBtn.title = error.message;
            saveBtn.classList.add('btn-error');

            setTimeout(() => {
                saveBtn.title = '';
                saveBtn.classList.remove('btn-error');
                setPopupState('ready');
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
            e.stopPropagation();
            settingsDropdown.classList.toggle('hidden');
        });

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
                setSafeHTML(bookmarksList, '<li class="empty-state">Start typing to search...</li>');
                return;
            }

            try {
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
        }, 300);
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
            li.className = 'recent-item';
            li.title = bookmark.url;

            const favSpan = document.createElement('span');
            favSpan.className = 'fav';
            li.appendChild(favSpan);

            const textNode = document.createTextNode(bookmark.title || bookmark.url);
            li.appendChild(textNode);

            li.addEventListener('click', () => {
                browser.tabs.create({ url: bookmark.url });
            });
            bookmarksList.appendChild(li);
        });
    }

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
        const storedAuth = await browser.storage.local.get('authToken');
        const storedJwt = await browser.storage.local.get(['accessToken', 'refreshToken']);
        if (storedAuth.authToken && !storedJwt.accessToken) {
            await browser.storage.local.remove('authToken');
        }

        if (storedJwt.accessToken && storedJwt.refreshToken) {
            api.setTokens(storedJwt.accessToken, storedJwt.refreshToken);
            showLogoutButton();
            loadRecent();
            await loadServerConfigAndVocab();
            await prepareCurrentTab();
        } else {
            if (tagsSection) tagsSection.classList.add('hidden');
            showLogin();
        }
    }

    function showLogoutButton() {
        if (document.getElementById('logout-btn')) return;

        const container = document.getElementById('logout-container');
        if (!container) return;

        const logoutBtn = document.createElement('button');
        logoutBtn.id = 'logout-btn';
        logoutBtn.title = 'Logout';
        logoutBtn.innerHTML = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>';
        logoutBtn.className = 'icon-btn';

        logoutBtn.addEventListener('click', async () => {
            abortInFlightSuggest();
            const stored = await browser.storage.local.get('refreshToken');
            const rt = stored.refreshToken;
            if (rt) {
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
            if (tagsSection) tagsSection.classList.add('hidden');
            showLogin();
        });

        container.appendChild(logoutBtn);
    }

    function showLogin() {
        const existingLogout = document.getElementById('logout-btn');
        if (existingLogout) existingLogout.remove();
        if (saveBtn) saveBtn.disabled = true;

        setSafeHTML(bookmarksList, `
            <div class="login-container">
                <p>Please login to save bookmarks.</p>
                <button id="login-btn" class="btn" style="background-color: #4285F4; box-shadow: none;">Login with Google</button>
                <div class="note">
                    Note: Requires configured Client ID
                </div>
            </div>
        `);

        document.getElementById('login-btn').addEventListener('click', async () => {
            try {
                setSafeHTML(bookmarksList, '<li class="empty-state">Authenticating...</li>');

                const CLIENT_ID = "127114677197-aei7k7s99vosi3hpqqti1v8h3r493te8.apps.googleusercontent.com";
                const REDIRECT_URI = browser.identity.getRedirectURL();
                const AUTH_URL = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${CLIENT_ID}&response_type=token&redirect_uri=${encodeURIComponent(REDIRECT_URI)}&scope=openid%20email%20profile`;

                const redirectUrl = await browser.identity.launchWebAuthFlow({
                    interactive: true,
                    url: AUTH_URL
                });

                if (redirectUrl) {
                    const url = new URL(redirectUrl);
                    const params = new URLSearchParams(url.hash.substring(1));
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
                        await loadServerConfigAndVocab();
                        await prepareCurrentTab();
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
                setTimeout(showLogin, 5000);
            }
        });
    }

    checkAuth();

    return {
        getState: () => popupState,
        getChips: () => chips.map(c => ({ ...c })),
        addUserChip,
        removeChipAt,
        requestSuggestions,
        prepareCurrentTab
    };
}

if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        globalThis.popupController = initPopup();
    });
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { initPopup };
}
