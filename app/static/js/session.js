/**
 * Per-tab conversation identity.
 *
 * The server keeps one agent per conversation, keyed by the id this file supplies.
 * It lives in sessionStorage rather than localStorage because sessionStorage is scoped
 * to a single tab: two tabs therefore hold two independent conversations, and neither
 * sees the other's poster, APR or chat history. A reload keeps the same id, so a
 * refresh mid-APR resumes the conversation instead of starting over.
 *
 * Loaded before the chat scripts so every API call carries the header.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'spicmacay_conversation_id';
    var HEADER = 'X-Conversation-Id';

    function newId() {
        if (window.crypto && window.crypto.randomUUID) {
            return window.crypto.randomUUID().replace(/-/g, '');
        }
        return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    }

    var conversationId;
    try {
        conversationId = window.sessionStorage.getItem(STORAGE_KEY);
        if (!conversationId) {
            conversationId = newId();
            window.sessionStorage.setItem(STORAGE_KEY, conversationId);
        }
    } catch (e) {
        // Private mode or storage disabled — fall back to a per-page-load id. The tab
        // still stays separate from other tabs; it just won't survive a reload.
        conversationId = newId();
    }

    window.CONVERSATION_ID = conversationId;

    /** Start a brand new conversation in this tab (used by the reset button). */
    window.newConversationId = function () {
        conversationId = newId();
        try {
            window.sessionStorage.setItem(STORAGE_KEY, conversationId);
        } catch (e) { /* nothing to persist to */ }
        window.CONVERSATION_ID = conversationId;
        return conversationId;
    };

    // Stamp the header on same-origin API calls, so every existing and future fetch
    // is covered without each call site having to remember
    var originalFetch = window.fetch;
    if (typeof originalFetch !== 'function') return;

    window.fetch = function (input, init) {
        var url = (typeof input === 'string') ? input : (input && input.url) || '';
        var isAbsolute = /^https?:\/\//i.test(url);
        var sameOrigin = !isAbsolute || url.indexOf(window.location.origin) === 0;

        if (!sameOrigin) {
            return originalFetch.apply(this, arguments);
        }

        var options = init ? Object.assign({}, init) : {};
        var headers = new Headers(options.headers || (typeof input === 'object' && input.headers) || {});
        headers.set(HEADER, window.CONVERSATION_ID);
        options.headers = headers;
        // Ensure the signed session cookie rides along; the id above is scoped under it
        if (!options.credentials) options.credentials = 'same-origin';

        return originalFetch.call(this, input, options);
    };
})();
