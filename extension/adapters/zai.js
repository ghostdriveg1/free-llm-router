/**
 * @fileoverview z.ai Chat adapter.
 * Targets the z.ai chat portal at chat.z.ai
 * Defines selectors, fetch patterns, and parsing logic specific to the z.ai web UI.
 * @module adapters/zai
 */

import { BaseAdapter, registerAdapter } from './base.js';

/**
 * z.ai Chat adapter.
 * @extends BaseAdapter
 */
class ZAIAdapter extends BaseAdapter {
  /** @returns {string} */
  get key() { return 'zai'; }

  /** @returns {string} */
  get name() { return 'z.ai'; }

  /** @returns {string[]} */
  get urlPatterns() {
    return [
      'chat.z.ai',
      'z.ai/chat',
      'z.ai',
    ];
  }

  /**
   * Input selectors in priority order for z.ai chat interface.
   * z.ai uses a contenteditable div similar to Kimi/Claude.
   * @returns {string[]}
   */
  get inputSelectors() {
    return [
      'div[contenteditable="true"][data-placeholder]',
      'div[contenteditable="true"][aria-label*="message"]',
      'div[contenteditable="true"][aria-label*="Message"]',
      'textarea[placeholder*="message"]',
      'textarea[placeholder*="Message"]',
      '[contenteditable="true"]',
      'textarea',
    ];
  }

  /**
   * Submit button selectors for z.ai.
   * @returns {string[]}
   */
  get submitSelectors() {
    return [
      'button[aria-label="Send"]',
      'button[aria-label="Send message"]',
      'button[aria-label="发送"]',  // Chinese: "Send"
      'button[data-testid="send-button"]',
      'button[type="submit"]',
      'button[class*="send"]',
      'div[class*="send-button"]',
      'span[class*="send"]',
    ];
  }

  /**
   * Selector for z.ai assistant response container.
   * @returns {string}
   */
  get responseSelector() {
    return [
      'div[data-role="assistant"]',
      'div[class*="assistant-message"]',
      'div[class*="ai-message"]',
      'div[class*="bot-message"]',
      'div[class*="message"][class*="assistant"]',
    ].join(', ');
  }

  /**
   * Streaming indicator for z.ai.
   * @returns {string}
   */
  get streamingIndicator() {
    return '[class*="streaming"], [class*="loading"], [class*="generating"], [class*="typing"]';
  }

  /**
   * z.ai internal API fetch patterns.
   * @returns {string[]}
   */
  get fetchPatterns() {
    return [
      '/v1/chat/completions',
      '/api/chat',
      '/chat/completions',
    ];
  }

  /**
   * Extract content delta from z.ai SSE chunk.
   * z.ai uses the standard OpenAI streaming format.
   * @param {object} json - Parsed JSON from SSE data line.
   * @returns {string|null}
   */
  extractContent(json) {
    try {
      // Try standard OpenAI format first
      const content = json?.choices?.[0]?.delta?.content;
      if (typeof content === 'string') return content;
      // Fallback to direct text field
      return json?.text || json?.content || null;
    } catch {
      return null;
    }
  }

  /**
   * Extract response text from z.ai DOM element.
   * @param {Element} el - The response container element.
   * @returns {string}
   */
  extractResponseText(el) {
    if (!el) return '';
    const markdownEl = el.querySelector('.markdown, [class*="markdown"], [class*="content"]');
    const target = markdownEl || el;
    return target.innerText?.trim() ?? target.textContent?.trim() ?? '';
  }

  /**
   * Check if z.ai is currently streaming.
   * @returns {boolean}
   */
  isStreaming() {
    if (document.querySelector('[class*="streaming"], [class*="typing-indicator"]')) return true;
    const stopBtn = document.querySelector('button[aria-label*="Stop"], button[aria-label*="stop"], button[aria-label*="停止"]');
    if (stopBtn) return true;
    return false;
  }
}

// ─── Register the adapter ────────────────────────────────────────
const zaiAdapter = new ZAIAdapter();
registerAdapter(zaiAdapter);

export default zaiAdapter;
export { ZAIAdapter };
