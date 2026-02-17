(function () {
    try {
        console.log("Starting extraction...");

        // Check libraries
        if (typeof Readability === 'undefined') throw new Error("Readability not loaded");
        if (typeof TurndownService === 'undefined') throw new Error("TurndownService not loaded");

        // Clone document
        const documentClone = document.cloneNode(true);
        const reader = new Readability(documentClone);
        const article = reader.parse();

        let contentMarkdown = "";
        let title = document.title;
        let extractionMethod = "readability";

        if (article && article.content) {
            const turndownService = new TurndownService({
                headingStyle: 'atx',
                codeBlockStyle: 'fenced'
            });
            contentMarkdown = turndownService.turndown(article.content);
            title = article.title || document.title;
        } else {
            console.warn("Readability failed, using fallback.");
            extractionMethod = "fallback_innerText";
            contentMarkdown = document.body.innerText;
        }

        return {
            title: title,
            url: window.location.href,
            content: contentMarkdown, // This matches what backend expects in 'content_markdown' but we'll map it
            extractionMethod: extractionMethod
        };

    } catch (e) {
        console.error("Extraction error:", e);
        return {
            error: e.toString(),
            title: document.title,
            url: window.location.href,
            content: document.body.innerText, // Ultimate fallback
            extractionMethod: "error_fallback"
        };
    }
})();
