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

## Packaging & Store Deployment

### Google Chrome Web Store Packaging (`deploy_chrome.ps1`)

To package the extension into a clean `.zip` archive ready for upload to the **Chrome Web Store Developer Dashboard**, run:

```powershell
.\deploy_chrome.ps1
```

This will:
- Auto-increment the patch version in `manifest.json` (e.g., `1.0.23` -> `1.0.24`).
- Stage clean source files in a temporary folder (excluding `.git`, `artifacts`, `INSTRUCTIONS.md`, temp files, etc.).
- Ensure `manifest.json` is at the root of the archive.
- Compress the extension into `Chrome Plugin\artifacts\chrome-plugin-v<Version>.zip`.
- Print direct links and instructions for manual upload to the [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole).

#### Advanced Options:
- **Package without incrementing version:**
  ```powershell
  .\deploy_chrome.ps1 -NoIncrement
  ```
- **Specify a custom version override:**
  ```powershell
  .\deploy_chrome.ps1 -Version "1.1.0"
  ```

---

### Microsoft Edge Add-ons Store Deployment (`deploy_edge.ps1`)

To distribute the extension through the **Microsoft Edge Add-ons Store**, you can package and deploy it using `deploy_edge.ps1` in the workspace root:

```powershell
.\deploy_edge.ps1
```


## Troubleshooting
- **"browser is not defined"**: Ensure you are running the extension from the `Chrome Plugin` folder.
- **Connection Errors**: Ensure the backend server is running (`localhost`). Check `api.js` base URL configuration in Options.

## Automatic Tagging Manual Verification Script

Run through these checks in the popup after loading the unpacked extension:

1. **Save Before Suggestion Returns**:
   - Open an `http(s)` article and click the extension icon.
   - Verify **Save Current Page** is enabled immediately once extraction succeeds (`Suggesting…` state).
   - Click **Save Current Page** before `/tags/suggest` finishes and verify the bookmark is saved with the current (possibly empty) chips.
2. **Merge User Edits With Delayed Suggestions**:
   - In DevTools Network tab (for the popup), throttle `/tags/suggest` (or add a 3 s delay on the server).
   - While `Suggesting…` is active, type a custom tag (e.g., `my-custom-tag`) and press `Enter`.
   - When the server response arrives, verify `my-custom-tag` is kept and non-conflicting suggested tags merge in alongside it.
3. **Removed Chip Not Re-added on Regenerate**:
   - Wait for suggestions to load, then click `×` on one suggested chip.
   - Click **↻ Regenerate** and verify the removed tag is not re-added.
4. **Stale Response Discarded on Rapid Regenerate**:
   - With network delay enabled on `/tags/suggest`, trigger **↻ Regenerate** while a suggestion request is already in flight.
   - Verify only the latest response updates the chip list and the earlier response is ignored.
5. **Submission Freezes Tags**:
   - Click **Save Current Page** while a suggestion request is in flight.
   - Verify the chip editor becomes read-only, the in-flight request is aborted, the saved bookmark's tags match the snapshot at click time, and no late response alters the UI or triggers a second save.
6. **Backend Down / Fallback**:
   - Stop the backend (or set `TAGGING_LLM_PROVIDER=off`) and open the popup.
   - Verify the hint displays `"No suggestions; add tags manually"` and manual tag entry + saving still works when the backend is reachable.
7. **Extraction Failure (`chrome://` page)**:
   - Open `chrome://extensions` and open the popup.
   - Verify **Save Current Page** is disabled and the **Retry** button is shown.


