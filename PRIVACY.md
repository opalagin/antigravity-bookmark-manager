# Privacy Policy for Smart Bookmark Manager (Microsoft Edge Extension)

**Last Updated:** June 15, 2026

This Privacy Policy explains how the **Smart Bookmark Manager** extension ("the Extension") for Microsoft Edge handles information. We are committed to protecting your privacy and ensuring you have complete control over your data.

---

## 1. Information We Collect and Process

In alignment with the Microsoft Edge developer data disclosures, the Extension processes only the following category of data:

*   **Website Content:** When you explicitly choose to bookmark a web page, the Extension extracts the text content and metadata of that specific page (the "Website Content") to index, summarize, and generate tags for it.

### What We Do NOT Collect
*   **Personally Identifiable Information (PII):** The Extension does not collect, record, or transmit any personally identifiable information (such as your name, email address, physical address, phone number, or IP address).
*   **Authentication Information:** The Extension does not collect, store, or transmit your authentication credentials (such as usernames, passwords, login tokens, or session identifiers). All API keys configured in the Extension (e.g., your AI backend URL or optional tokens) are stored strictly locally on your device.

---

## 2. How Your Information is Used

The processed Website Content is used solely to provide the core functionality of the Extension:
*   Indexing your bookmarks to make them searchable.
*   Generating automatic AI summaries and relevant categorization tags.
*   Answering natural language questions about your bookmarked pages.

---

## 3. Data Storage, Hosting, and Third-Party Transmission

The Extension is designed with a self-hosted architecture, meaning you maintain complete ownership of your data environment:

*   **Local Storage:** Your configuration preferences and settings (such as the base URL of your Search Backend) are stored locally on your device using the Microsoft Edge secure extension storage API (`chrome.storage.local`).
*   **Self-Hosted Backend:** The extracted Website Content is transmitted directly to your own self-hosted **Search Backend** (e.g. running locally via Docker or deployed on your private Railway hosting) and stored in your private database (e.g., PostgreSQL). **No data is sent to the Extension developer.**
*   **Third-Party AI Services:** To generate summaries and answer questions, Website Content may be sent from your private Search Backend to your configured AI provider (such as the OpenAI API or a locally hosted LLM). This data transmission is governed by your agreement and the privacy policy of the selected AI provider.

---

## 4. User Control, Access, and Deletion

Under Microsoft Edge Developer Policy 1.5.2, you have complete control over your data:
*   **Access:** You have full access to all saved Website Content through your self-hosted backend database or the Extension's interface.
*   **Deletion:** You can delete your bookmarks and their associated Website Content at any time directly through the Extension's management dashboard, which will permanently purge the content from your self-hosted database.
*   **Settings Reset:** You can clear all locally stored extension options and API tokens by uninstalling the Extension or clearing the extension data in Microsoft Edge (`edge://extensions`).

---

## 5. Compliance with Laws

This policy is designed to comply with global privacy regulations, including the General Data Protection Regulation (GDPR) and the California Consumer Privacy Act (CCPA). Because you host the backend database, you are the sole controller of the stored data.

---

## 6. Changes to This Policy

We may update this Privacy Policy from time to time to reflect changes in our features or legal requirements. The updated policy will be posted on this page with an updated "Last Updated" date.

---

## 7. Contact Us

If you have any questions or feedback about this Privacy Policy, please contact the developer at:
*   **Developer Contact:** apalagin at outlook.com
