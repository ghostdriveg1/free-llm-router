/**
 * @fileoverview Kimi provider adapter.
 * @module adapters/kimi
 */

import { BaseAdapter, registerAdapter } from './base.js';

class KimiAdapter extends BaseAdapter {
  get key() { return 'kimi'; }
  get name() { return 'Kimi'; }
  get urlPatterns() { return ['kimi.moonshot.cn']; }
  get inputSelectors() {
    return [
      '[contenteditable="true"]',
      'textarea',
    ];
  }
  get submitSelectors() {
    return [
      'button[class*="send"]',
      'button[type="submit"]',
    ];
  }
  get responseSelector() {
    return 'div[class*="assistant"]';
  }
  get streamingIndicator() {
    return '.streaming-indicator, [class*="streaming"]';
  }
}

const kimiAdapter = new KimiAdapter();
registerAdapter(kimiAdapter);

export default kimiAdapter;
export { KimiAdapter };
