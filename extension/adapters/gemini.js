/**
 * @fileoverview Gemini provider adapter.
 * @module adapters/gemini
 */

import { BaseAdapter, registerAdapter } from './base.js';

class GeminiAdapter extends BaseAdapter {
  get key() { return 'gemini'; }
  get name() { return 'Gemini'; }
  get urlPatterns() { return ['gemini.google.com']; }
  get inputSelectors() {
    return [
      'div[contenteditable="true"][aria-label="Prompt"]',
      'textarea',
      '[contenteditable="true"]',
    ];
  }
  get submitSelectors() {
    return [
      'button[aria-label="Send message"]',
      'button[class*="send"]',
      'div[aria-label="Send message"] button',
    ];
  }
  get responseSelector() {
    return '.message-content, [data-message-author-role="assistant"], div.model-response';
  }
  get streamingIndicator() {
    return '.generating, .streaming, [class*="generating"]';
  }
}

const geminiAdapter = new GeminiAdapter();
registerAdapter(geminiAdapter);

export default geminiAdapter;
export { GeminiAdapter };
