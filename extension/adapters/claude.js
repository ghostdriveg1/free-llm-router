/**
 * @fileoverview Claude provider adapter.
 * @module adapters/claude
 */

import { BaseAdapter, registerAdapter } from './base.js';

class ClaudeAdapter extends BaseAdapter {
  get key() { return 'claude'; }
  get name() { return 'Claude'; }
  get urlPatterns() { return ['claude.ai']; }
  get inputSelectors() {
    return [
      '[contenteditable="true"]',
      'textarea',
    ];
  }
  get submitSelectors() {
    return [
      'button[aria-label="Send Message"]',
      'button[class*="send"]',
    ];
  }
  get responseSelector() {
    return 'div[class*="assistant-message"]';
  }
  get streamingIndicator() {
    return '.generating, [class*="generating"]';
  }
}

const claudeAdapter = new ClaudeAdapter();
registerAdapter(claudeAdapter);

export default claudeAdapter;
export { ClaudeAdapter };
