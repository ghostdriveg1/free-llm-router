/**
 * @fileoverview NVIDIA NIM Portal adapter.
 * Targets the NVIDIA NIM playground at build.nvidia.com
 * Defines selectors, fetch patterns, and parsing logic specific to the NIM web UI.
 * @module adapters/nim
 */

import { BaseAdapter, registerAdapter } from './base.js';

/**
 * NVIDIA NIM Portal adapter.
 * @extends BaseAdapter
 */
class NIMAdapter extends BaseAdapter {
  /** @returns {string} */
  get key() { return 'nim'; }

  /** @returns {string} */
  get name() { return 'NVIDIA NIM'; }

  /** @returns {string[]} */
  get urlPatterns() {
    return [
      'build.nvidia.com',
      'nim.developer.nvidia.com',
    ];
  }

  /**
   * Input selectors in priority order for NIM playground chat input.
   * NIM uses a standard textarea with a specific placeholder.
   * @returns {string[]}
   */
  get inputSelectors() {
    return [
      'textarea[placeholder*="message"]',
      'textarea[placeholder*="Message"]',
      'textarea[data-testid="chat-input"]',
      'div[contenteditable="true"]',
      'textarea',
    ];
  }

  /**
   * Submit button selectors for NIM playground.
   * @returns {string[]}
   */
  get submitSelectors() {
    return [
      'button[aria-label="Send"]',
      'button[aria-label="Send message"]',
      'button[type="submit"]',
      'button[data-testid="send-button"]',
      // NIM often has an icon button near the textarea
      'form button:last-child',
      'div[role="button"][aria-label*="send"]',
    ];
  }

  /**
   * Selector for the NIM assistant response container.
   * @returns {string}
   */
  get responseSelector() {
    return [
      'div[data-role="assistant"]',
      'div[class*="assistant"]',
      'div[class*="message"][class*="response"]',
      'div[class*="chat-message"]:last-child',
    ].join(', ');
  }

  /**
   * Streaming indicator — visible while NIM is generating.
   * @returns {string}
   */
  get streamingIndicator() {
    return '[class*="streaming"], [class*="loading"], [class*="generating"], div[class*="cursor-blink"]';
  }

  /**
   * NIM playground internal API fetch patterns.
   * @returns {string[]}
   */
  get fetchPatterns() {
    return [
      '/v1/chat/completions',
      '/api/v1/chat',
    ];
  }

  /**
   * Extract content delta from NIM SSE chunk.
   * NIM uses the standard OpenAI chunk format since it IS the NIM API.
   * @param {object} json - Parsed JSON from SSE data line.
   * @returns {string|null}
   */
  extractContent(json) {
    try {
      // Standard OpenAI streaming format
      const content = json?.choices?.[0]?.delta?.content;
      return typeof content === 'string' ? content : null;
    } catch {
      return null;
    }
  }

  /**
   * Extract response text from NIM response DOM element.
   * @param {Element} el - The response container element.
   * @returns {string}
   */
  extractResponseText(el) {
    if (!el) return '';
    const codeEl = el.querySelector('pre, code');
    if (codeEl) return codeEl.innerText?.trim() ?? '';
    return el.innerText?.trim() ?? el.textContent?.trim() ?? '';
  }

  /**
   * Check if NIM is currently streaming.
   * @returns {boolean}
   */
  isStreaming() {
    if (document.querySelector('[class*="streaming"], [class*="cursor-blink"]')) return true;
    // Check if there's a stop button visible
    const stopBtn = document.querySelector('button[aria-label*="Stop"], button[aria-label*="stop"]');
    if (stopBtn) return true;
    return false;
  }
}

// ─── Register the adapter ────────────────────────────────────────
const nimAdapter = new NIMAdapter();
registerAdapter(nimAdapter);

export default nimAdapter;
export { NIMAdapter };
