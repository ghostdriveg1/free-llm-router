/**
 * @fileoverview ChatGPT provider adapter.
 * Defines selectors, fetch patterns, and parsing logic
 * specific to the ChatGPT web UI (chat.openai.com / chatgpt.com).
 * @module adapters/chatgpt
 */

import { BaseAdapter, registerAdapter } from './base.js';

/**
 * ChatGPT adapter for the OpenAI web interface.
 * @extends BaseAdapter
 */
class ChatGPTAdapter extends BaseAdapter {
  /** @returns {string} */
  get key() { return 'chatgpt'; }

  /** @returns {string} */
  get name() { return 'ChatGPT'; }

  /** @returns {string[]} */
  get urlPatterns() {
    return [
      'chat.openai.com',
      'chatgpt.com',
    ];
  }

  /**
   * Input selectors tried in priority order.
   * ChatGPT has changed its input element several times:
   * - #prompt-textarea (classic textarea)
   * - div#prompt-textarea[contenteditable] (newer ProseMirror-based)
   * - [contenteditable="true"] (fallback)
   * @returns {string[]}
   */
  get inputSelectors() {
    return [
      '#prompt-textarea',
      'div[contenteditable="true"][id="prompt-textarea"]',
      'textarea[data-id="root"]',
      '[contenteditable="true"]',
    ];
  }

  /**
   * Submit button selectors.
   * ChatGPT uses data-testid on the send button, but it changes.
   * @returns {string[]}
   */
  get submitSelectors() {
    return [
      'button[data-testid="send-button"]',
      'button[data-testid="fruitjuice-send-button"]',
      'button[aria-label="Send prompt"]',
      'form button[class*="bottom"]',
      // Fallback: look for the button near the textarea
      '#prompt-textarea ~ button',
      '#composer-background button[aria-label]',
    ];
  }

  /**
   * Selector for assistant response containers.
   * We want the last one on the page.
   * @returns {string}
   */
  get responseSelector() {
    return [
      '[data-message-author-role="assistant"]',
      'div[class*="markdown"]',
    ].join(', ');
  }

  /**
   * Streaming indicator — present while ChatGPT is still generating.
   * @returns {string}
   */
  get streamingIndicator() {
    return '.result-streaming, [class*="result-streaming"]';
  }

  /**
   * URL patterns for ChatGPT's conversation API endpoint.
   * @returns {string[]}
   */
  get fetchPatterns() {
    return [
      '/backend-api/conversation',
    ];
  }

  /**
   * Extract content delta from a ChatGPT SSE JSON chunk.
   *
   * ChatGPT SSE format (simplified):
   * ```json
   * {
   *   "message": {
   *     "content": {
   *       "parts": ["Hello, how can I help?"],
   *       "content_type": "text"
   *     },
   *     "author": { "role": "assistant" },
   *     "status": "in_progress"
   *   }
   * }
   * ```
   *
   * We extract the last part from message.content.parts.
   *
   * @param {object} json - Parsed JSON from SSE data line.
   * @returns {string|null} Extracted text content or null.
   */
  extractContent(json) {
    try {
      // Handle the standard conversation SSE format
      const message = json?.message;
      if (!message) return null;

      // Only extract from assistant messages
      const role = message?.author?.role;
      if (role !== 'assistant') return null;

      // Skip non-text content
      const contentType = message?.content?.content_type;
      if (contentType !== 'text') return null;

      const parts = message?.content?.parts;
      if (!Array.isArray(parts) || parts.length === 0) return null;

      // Return the full accumulated text (last part)
      const text = parts[parts.length - 1];
      return typeof text === 'string' ? text : null;
    } catch {
      return null;
    }
  }

  /**
   * Extract response text from a ChatGPT response DOM element.
   * Handles the markdown rendering container.
   * @param {Element} el - The response container element.
   * @returns {string} Extracted text.
   */
  extractResponseText(el) {
    if (!el) return '';

    // Try to find the markdown container within the response
    const markdownEl = el.querySelector('.markdown, [class*="markdown"]');
    const target = markdownEl || el;

    // Use innerText for cleaner output (respects CSS display)
    return target.innerText?.trim() ?? target.textContent?.trim() ?? '';
  }

  /**
   * Find the last assistant response element specifically for ChatGPT.
   * Overrides base to handle ChatGPT's DOM structure.
   * @returns {Element|null}
   */
  findLastResponse() {
    // Primary: data-message-author-role attribute
    const byRole = document.querySelectorAll('[data-message-author-role="assistant"]');
    if (byRole.length > 0) {
      return byRole[byRole.length - 1];
    }

    // Fallback: look for turn containers
    const turns = document.querySelectorAll('[data-testid^="conversation-turn"]');
    if (turns.length > 0) {
      // Get the last turn that contains assistant content
      for (let i = turns.length - 1; i >= 0; i--) {
        const turn = turns[i];
        if (turn.querySelector('[data-message-author-role="assistant"]') ||
            turn.querySelector('.markdown')) {
          return turn;
        }
      }
    }

    return null;
  }

  /**
   * Check if ChatGPT is currently streaming.
   * @returns {boolean}
   */
  isStreaming() {
    // Check for the streaming class
    if (document.querySelector('.result-streaming')) return true;

    // Check for the stop button (visible during generation)
    const stopBtn = document.querySelector('button[aria-label="Stop generating"]');
    if (stopBtn) return true;

    return false;
  }
}

// ─── Register the adapter ────────────────────────────────────────
const chatgptAdapter = new ChatGPTAdapter();
registerAdapter(chatgptAdapter);

export default chatgptAdapter;
export { ChatGPTAdapter };
