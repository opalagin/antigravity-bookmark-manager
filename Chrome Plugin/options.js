const DEFAULT_API_URL = "http://localhost";

function saveOptions(e) {
    e.preventDefault();
    let url = document.querySelector("#apiUrl").value;
    // Strip trailing slash if present
    if (url.endsWith('/')) {
        url = url.slice(0, -1);
    }

    if (!url) {
        url = DEFAULT_API_URL;
    }

    chrome.storage.local.set({
        apiUrl: url
    }).then(() => {
        const status = document.getElementById("status");
        status.style.display = "block";
        setTimeout(() => {
            status.style.display = "none";
        }, 2000);
    });
}

function restoreOptions() {
    chrome.storage.local.get("apiUrl").then((result) => {
        document.querySelector("#apiUrl").value = result.apiUrl || DEFAULT_API_URL;
    });
}

document.addEventListener("DOMContentLoaded", restoreOptions);
document.querySelector("#save").addEventListener("click", saveOptions);
