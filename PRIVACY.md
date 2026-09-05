# Privacy Policy for Smart Bookmark Manager

**Last Updated:** September 4, 2026

This Privacy Policy explains how the **Smart Bookmark Manager** extension ("the Extension") for Google Chrome, Microsoft Edge, and Mozilla Firefox handles user information. We are committed to protecting your privacy, adhering to the Google Chrome Web Store User Data Policy, and ensuring you maintain full control over your data.

---

## 1. Information We Collect and Process

The Extension only processes data necessary to fulfill its single purpose: saving, organizing, and retrieving personal bookmarks with AI assistance.

### A. Information You Provide Directly
* **Website Content:** When you explicitly click "Save Bookmark", the Extension captures the current webpage URL, page title, and main article text (extracted client-side using Readability) to index and summarize it. The Extension **does not** track or record pages you do not explicitly choose to save.
* **Search & Chat Queries:** Questions and keywords you enter into the search bar or AI companion side panel to retrieve information from your bookmarked knowledge base.

### B. Authentication & Session Data
* **Google Account Authentication:** When you choose to sign in via Google OAuth (`chrome.identity.launchWebAuthFlow`), an authentication token is transmitted securely to your backend API server to verify your identity and generate session tokens.
* **Local Session Tokens:** Secure session tokens (JWT access and refresh tokens) and user configuration settings (such as your backend API endpoint URL) are stored locally on your device using `chrome.storage.local`.

### C. What We Do NOT Collect
* **No Browsing History Tracking:** The Extension does not monitor, log, or transmit your overall browsing activity or search engine queries.
* **No Financial or Sensitive Personal Data:** The Extension does not collect credit card numbers, health data, or government identifiers.
* **No Third-Party Advertising Trackers:** The Extension contains no ads, ad-tracking pixels, or third-party behavioral analytics SDKs.

---

## 2. How Your Information Is Used

Data processed by the Extension is used strictly to provide its core features:
1. Indexing your saved bookmarks to make them searchable.
2. Generating AI-assisted summaries and automated tags for saved articles.
3. Enabling natural language question-answering over your saved reading list via the side panel and popup.
4. Authenticating you with your designated backend service.

---

## 3. Google Chrome Web Store Policy Disclosures

In compliance with the **Google Chrome Web Store User Data Policy** and **Limited Use** requirements:

* **Not Sold to Third Parties:** We do **NOT** sell, rent, or monetize your personal data or bookmarked content to data brokers, advertising networks, or any other third parties.
* **No Unrelated Transfers:** We do **NOT** transfer your data for purposes unrelated to the core functionality of the Extension (saving and searching bookmarks).
* **No Creditworthiness or Lending Use:** We do **NOT** use or transfer your data to determine creditworthiness or for lending purposes.
* **Human Review:** No humans read your bookmarked content or private search queries, except if you explicitly request technical support and share specific error logs or snippets.

---

## 4. Data Storage, Architecture, and Third-Party Services

The Extension operates in conjunction with a user-configured backend service:

* **Local Storage on Device:** Tokens and configuration preferences reside strictly within your browser's protected local storage (`chrome.storage.local`).
* **Backend API Server:** Saved bookmarks and chat queries are transmitted over encrypted HTTPS/HTTP to your designated backend server (e.g., your self-hosted Docker instance or deployed cloud backend on Railway).
* **Third-Party AI Providers:** To generate AI summaries and answer queries, bookmark text may be processed through an AI provider configured on the backend (such as OpenAI API or a self-hosted LLM). Such data handling is strictly limited to processing your requested prompt/summary and subject to the respective provider's API privacy terms.

---

## 5. User Control, Data Retention, and Deletion

You have complete authority over your data:

* **Access & Edit:** You can view, search, and edit all your saved bookmarks at any time via the Manager page (`manager.html`) or the Side Panel.
* **Deletion:** You can delete individual bookmarks or purge all saved items directly from the Extension management UI, which removes them from the backend database.
* **Account / Token Removal:** You can log out at any time or uninstall the Extension. Uninstalling the Extension or clearing extension data (`chrome://extensions`) immediately purges all local tokens and configurations from your device.

---

## 6. Security

We take reasonable and appropriate technical measures to protect your information:
* All communication with external and backend services occurs over standard secure network protocols.
* Authentication tokens are stored in sandboxed browser extension storage inaccessible to unauthorized web pages.

---

## 7. Changes to This Privacy Policy

We may update this Privacy Policy from time to time to reflect feature enhancements or regulatory changes. Any revisions will be reflected with an updated "Last Updated" date at the top of this document.

---

## 8. Contact Us

If you have questions, concerns, or requests regarding this Privacy Policy or your data, please contact:
* **Developer:** Alex Palagin
* **Email:** apalagin@outlook.com
* **Repository:** https://github.com/opalagin/antigravity-bookmark-manager
