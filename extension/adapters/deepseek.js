/**
 * @fileoverview DeepSeek provider adapter.
 * @module adapters/deepseek
 */

import { BaseAdapter, registerAdapter } from './base.js';

class DeepSeekAdapter extends BaseAdapter {
  get key() { return 'deepseek'; }
  get name() { return 'DeepSeek'; }
  get urlPatterns() { return ['chat.deepseek.com']; }
  get inputSelectors() {
    return [
      'textarea',
      '#chat-input',
      '[contenteditable="true"]',
    ];
  }
  get submitSelectors() {
    return [
      'button[aria-label="Send message"]',
      'div[class*="send-button"]',
      'button[class*="send"]',
    ];
  }
  get responseSelector() {
    return 'div[class*="assistant-message"]';
  }
  get streamingIndicator() {
    return 'div[class*="streaming"], div[class*="loading"]';
  }
}

const deepseekAdapter = new DeepSeekAdapter();
registerAdapter(deepseekAdapter);

export default deepseekAdapter;
export { DeepSeekAdapter };
