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

To distribute the extension through the **Microsoft Edge Add-ons Store**, you can package it into a production-ready `.zip` archive using the PowerShell script `deploy_edge.ps1` in the workspace root.

### Deployment Workflow
1. **Manual Upload (Initial Submission):** Microsoft requires the first version of any extension to be submitted manually via the Partner Center dashboard. The script will generate the clean `.zip` archive for you.
2. **Automated Submission (Subsequent Updates):** Once the extension is created, you can generate API credentials in the Partner Center and save them in `.env`. The script will then automatically upload and publish updates to the store using the Microsoft Edge Add-ons REST API.

### Running the Deployment Script

1. Open PowerShell in the workspace root.
2. Run the deployment script:
   ```powershell
   .\deploy_edge.ps1
   ```
   This will:
   - Auto-increment the patch version of the extension in `manifest.json` (e.g. `1.0.18` -> `1.0.19`).
   - Copy only the required source files to a clean temporary folder (ignoring development files and previous artifacts).
   - Compress the files into `Chrome Plugin\artifacts\chrome-plugin-v<Version>.zip`.
   - Check your local `.env` file for:
     - `EDGE_PRODUCT_ID`
     - `EDGE_CLIENT_ID`
     - `EDGE_API_KEY`
   - **If keys are missing:** Complete the run by outputting the path to the `.zip` file and instructions on how to manually upload it to the Partner Center.
   - **If keys are present:** Authenticate using Microsoft's REST API v1.1, upload the new package, poll the server to verify processing, and automatically request publication.

3. Alternatively, specify a custom version override:
   ```powershell
   .\deploy_edge.ps1 -Version "1.1.0"
   ```


## Troubleshooting
- **"browser is not defined"**: Ensure you are running the extension from the `Chrome Plugin` folder.
- **Connection Errors**: Ensure the backend server is running (`localhost`). Check `api.js` base URL configuration in Options.

