# Chrome Plugin Installation & Debugging

## Installation

1.  Open **Chrome** and navigate to `chrome://extensions`.
2.  Enable **Developer mode** (toggle in the top right corner).
3.  Click the **Load unpacked** button.
4.  Select the **`Chrome Plugin`** folder inside the `AI Bookmark Manager v1` directory.
5.   The "Smart Bookmark Manager" extension should appear in the list.

## Debugging

### Inspecting the Popup
- Click the extension icon in the toolbar.
- Right-click anywhere inside the popup and select **Inspect**.
- This opens the DevTools for the popup context (`popup.html` / `popup.js`).

### Inspecting the Side Panel
- Open the Side Panel (via the extension icon or Chrome menu).
- Right-click anywhere in the side panel and select **Inspect**.
- This opens the DevTools for the sidebar context (`sidebar.html` / `sidebar.js`).

### Inspecting the Service Worker (Background)
- Go to `chrome://extensions`.
- Find "Smart Bookmark Manager".
- Click the **service worker** link (next to "Inspect views").
- This opens the DevTools for the background script (`background.js`).

## Key Changes from Firefox Version
- **Namespace**: `chrome.*` API used instead of `browser.*`.
- **Manifest**: Converted to Manifest V3 for Chrome.
    - `background` converted to `service_worker`.
    - `sidebar_action` replaced with `side_panel`.
- **Permissions**: `sidePanel` permission added.

## Troubleshooting
- **"browser is not defined"**: Ensure you are running the extension from the `Chrome Plugin` folder.
- **Connection Errors**: Ensure the backend server is running (`localhost`). Check `api.js` base URL configuration in Options.
