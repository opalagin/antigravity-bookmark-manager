document.addEventListener('DOMContentLoaded', () => {
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const history = document.getElementById('chat-history');

    // Auto-resize textarea
    chatInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        sendBtn.disabled = !this.value.trim();
    });

    // Handle Send
    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // 1. Add User Message
        appendMessage(text, 'user');
        chatInput.value = '';
        chatInput.style.height = 'auto';
        sendBtn.disabled = true;

        // 2. Add Loading State
        const loadingId = appendMessage('Is thinking...', 'ai', true);

        try {
            // 3. Call API
            if (!window.api) throw new Error("API not loaded");
            const response = await window.api.chat(text);

            // 4. Update AI Message
            updateMessage(loadingId, response.answer);

        } catch (error) {
            console.error(error);
            updateMessage(loadingId, "Sorry, something went wrong: " + error.message);
        }
    }

    sendBtn.addEventListener('click', sendMessage);

    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // --- Helpers ---

    function appendMessage(text, type, isLoading = false) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${type}-message`;
        if (isLoading) msgDiv.classList.add('loading');

        const contentDiv = document.createElement('div');
        contentDiv.className = 'content';
        contentDiv.textContent = text;

        msgDiv.appendChild(contentDiv);
        history.appendChild(msgDiv);
        history.scrollTop = history.scrollHeight;

        return msgDiv; // Return element for updates
    }

    function updateMessage(element, newText) {
        element.classList.remove('loading');
        const contentDiv = element.querySelector('.content');

        // Simple Markdown-ish rendering (just newlines for now)
        // In a real app, use a library like 'marked'
        contentDiv.innerHTML = newText.replace(/\n/g, '<br>');
        history.scrollTop = history.scrollHeight;
    }
});
