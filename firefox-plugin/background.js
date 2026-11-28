globalThis.browser = globalThis.browser || (typeof chrome !== 'undefined' ? chrome : null);

const ICON_DEFAULT = {
    16: "icons/icon-16.png",
    32: "icons/icon-32.png",
    48: "icons/icon-48.png",
    128: "icons/icon-128.png"
};

const ICON_SAVED = {
    16: "icons/icon-saved-16.png",
    32: "icons/icon-saved-32.png",
    48: "icons/icon-saved-48.png",
    128: "icons/icon-saved-128.png"
};

const SYNC_INTERVAL_MS = 10 * 60 * 1000;
const RETRY_BACKOFF_MS = 60 * 1000;

let bookmarkedUrls = new Set();
let syncedAt = 0;
let lastAttemptAt = 0;
let loadedFromStorage = false;
let authGeneration = 0;
let syncPromise = null;
let syncDirty = false;
let pendingSavedUrls = new Set();

async function ensureLoaded() {
    if (loadedFromStorage) return;
    const data = await browser.storage.local.get([
        "bookmarkedUrls",
        "bookmarkedUrlsSyncedAt"
    ]);
    if (Array.isArray(data.bookmarkedUrls)) {
        bookmarkedUrls = new Set(data.bookmarkedUrls);
    }
    if (typeof data.bookmarkedUrlsSyncedAt === "number") {
        syncedAt = data.bookmarkedUrlsSyncedAt;
    }
    loadedFromStorage = true;
}

async function paintTab(tab) {
    if (!tab || typeof tab.id !== "number") return;
    const saved = !!tab.url && bookmarkedUrls.has(tab.url);
    try {
        await browser.action.setIcon({
            tabId: tab.id,
            path: saved ? ICON_SAVED : ICON_DEFAULT
        });
        await browser.action.setTitle({
            tabId: tab.id,
            title: saved ? "Smart Bookmark Manager — saved" : "Smart Bookmark Manager"
        });
    } catch (_e) {
        // Tab may have closed mid-call
    }
}

async function repaintAllTabs() {
    try {
        const tabs = await browser.tabs.query({});
        await Promise.all(tabs.map(paintTab));
    } catch (_e) {
        // Ignore tab query errors
    }
}

function syncBookmarkedUrls({ force = false } = {}) {
    if (syncPromise && !force) return syncPromise;

    const myGen = authGeneration;
    lastAttemptAt = Date.now();
    syncDirty = false;
    pendingSavedUrls.clear();

    const thisPromise = (async () => {
        try {
            const { apiUrl, accessToken } = await browser.storage.local.get([
                "apiUrl",
                "accessToken"
            ]);
            if (myGen !== authGeneration || !accessToken) return;

            const baseUrl = apiUrl || "http://localhost";
            const response = await fetch(`${baseUrl}/bookmarks/urls`, {
                method: "GET",
                headers: {
                    Authorization: `Bearer ${accessToken}`
                }
            });

            if (myGen !== authGeneration || !response.ok) {
                // Discard stale-session responses; keep last known set on 401/errors
                return;
            }

            const data = await response.json();
            if (myGen !== authGeneration) return;

            if (Array.isArray(data.urls)) {
                bookmarkedUrls = new Set([...data.urls, ...pendingSavedUrls]);
                syncedAt = Date.now();
                loadedFromStorage = true;
                await browser.storage.local.set({
                    bookmarkedUrls: Array.from(bookmarkedUrls),
                    bookmarkedUrlsSyncedAt: syncedAt
                });
                if (myGen === authGeneration) {
                    await repaintAllTabs();
                }
            }
        } catch (_e) {
            // Keep last known set on network errors
        } finally {
            if (syncPromise === thisPromise) {
                syncPromise = null;
            }
            if (myGen === authGeneration && syncDirty) {
                syncDirty = false;
                syncBookmarkedUrls();
            }
        }
    })();

    syncPromise = thisPromise;
    return thisPromise;
}

function maybeStaleSync() {
    const now = Date.now();
    if (now - syncedAt <= SYNC_INTERVAL_MS) return;
    if (now - lastAttemptAt < RETRY_BACKOFF_MS) return;
    syncBookmarkedUrls();
}

browser.runtime.onStartup.addListener(async () => {
    await ensureLoaded();
    await repaintAllTabs();
    await syncBookmarkedUrls();
});

browser.runtime.onInstalled.addListener(async () => {
    await ensureLoaded();
    await repaintAllTabs();
    await syncBookmarkedUrls();
});

browser.storage.onChanged.addListener(async (changes, areaName) => {
    if (areaName !== "local") return;

    if (changes.apiUrl) {
        authGeneration += 1;
        syncDirty = false;
        pendingSavedUrls.clear();
        syncPromise = null;
        bookmarkedUrls = new Set();
        syncedAt = 0;
        lastAttemptAt = 0;
        loadedFromStorage = true;
        await browser.storage.local.remove([
            "bookmarkedUrls",
            "bookmarkedUrlsSyncedAt"
        ]);
        await repaintAllTabs();
        const { accessToken } = await browser.storage.local.get("accessToken");
        if (accessToken) {
            await syncBookmarkedUrls({ force: true });
        }
        return;
    }

    if (changes.accessToken) {
        authGeneration += 1;
        syncDirty = false;
        pendingSavedUrls.clear();
        syncPromise = null;
        lastAttemptAt = 0;
        if (changes.accessToken.newValue) {
            await syncBookmarkedUrls({ force: true });
        } else {
            bookmarkedUrls = new Set();
            syncedAt = 0;
            loadedFromStorage = true;
            await browser.storage.local.remove([
                "bookmarkedUrls",
                "bookmarkedUrlsSyncedAt"
            ]);
            await repaintAllTabs();
        }
    }
});

browser.runtime.onMessage.addListener((message) => {
    if (!message || typeof message.type !== "string") return;

    if (message.type === "bookmark-saved" && typeof message.url === "string") {
        (async () => {
            await ensureLoaded();
            if (syncPromise) {
                pendingSavedUrls.add(message.url);
                syncDirty = true;
            }
            if (!bookmarkedUrls.has(message.url)) {
                bookmarkedUrls.add(message.url);
                await browser.storage.local.set({
                    bookmarkedUrls: Array.from(bookmarkedUrls)
                });
            }
            try {
                const tabs = await browser.tabs.query({});
                await Promise.all(
                    tabs.filter((t) => t.url === message.url).map(paintTab)
                );
            } catch (_e) {
                // Ignore
            }
        })();
    } else if (message.type === "bookmarks-changed") {
        lastAttemptAt = 0;
        if (syncPromise) {
            syncDirty = true;
        } else {
            syncBookmarkedUrls();
        }
    }
});

browser.tabs.onUpdated.addListener(async (_tabId, changeInfo, tab) => {
    if (!changeInfo.url && changeInfo.status !== "complete") return;
    await ensureLoaded();
    await paintTab(tab);
    maybeStaleSync();
});

browser.tabs.onActivated.addListener(async (activeInfo) => {
    await ensureLoaded();
    try {
        const tab = await browser.tabs.get(activeInfo.tabId);
        await paintTab(tab);
    } catch (_e) {
        // Tab may have closed
    }
    maybeStaleSync();
});
