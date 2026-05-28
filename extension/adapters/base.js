/**
 * @fileoverview Base adapter interface and provider registry.
 * Each provider adapter defines selectors, URL patterns, and
 * parsing logic specific to its chatbot UI.
 * @module adapters/base
 */

/**
 * @typedef {Object} AdapterConfig
 * @property {string}   key             - Internal provider key (e.g. "chatgpt").
 * @property {string}   name            - Human-readable name.
 * @property {string[]} urlPatterns     - URL patterns to match this provider.
 * @property {string[]} inputSelectors  - CSS selectors for the input field (tried in order).
 * @property {string[]} submitSelectors - CSS selectors for the submit/send button.
 * @property {string}   responseSelector - CSS selector for the last assistant response.
 * @property {string}   streamingIndicator - CSS selector/class indicating streaming in progress.
 * @property {string[]} fetchPatterns   - URL substrings to match API fetch calls.
 * @property {function(object): string|null} extractContent - Extract text content from a parsed SSE JSON chunk.
 * @property {function(Element): string} extractResponseText - Extract response text from a DOM element.
 */

/**
 * Base adapter with sensible defaults. Provider-specific adapters
 * override the fields they need.
 */
export class BaseAdapter {
  /** @returns {string} */
  get key() { return 'unknown'; }

  /** @returns {string} */
  get name() { return 'Unknown Provider'; }

  /** @returns {string[]} */
  get urlPatterns() { return []; }

  /** @returns {string[]} */
  get inputSelectors() { return ['textarea', '[contenteditable="true"]']; }

  /** @returns {string[]} */
  get submitSelectors() { return ['button[type="submit"]']; }

  /** @returns {string} */
  get responseSelector() { return ''; }

  /** @returns {string} */
  get streamingIndicator() { return ''; }

  /** @returns {string[]} */
  get fetchPatterns() { return []; }

  /**
   * Extract content delta from a parsed SSE JSON chunk.
   * Override in provider adapters.
   * @param {object} json - Parsed JSON from SSE data field.
   * @returns {string|null} Content text or null if not a content chunk.
   */
  extractContent(json) {
    return null;
  }

  /**
   * Extract the full response text from a DOM element.
   * @param {Element} el - The response container element.
   * @returns {string} Extracted text.
   */
  extractResponseText(el) {
    if (!el) return '';
    // Default: use innerText for clean text extraction
    return el.innerText?.trim() ?? el.textContent?.trim() ?? '';
  }

  /**
   * Check if a URL matches this provider.
   * @param {string} url - The page URL to test.
   * @returns {boolean}
   */
  matchesUrl(url) {
    return this.urlPatterns.some(pattern => url.includes(pattern));
  }

  /**
   * Check if a fetch URL matches this provider's API patterns.
   * @param {string} fetchUrl - The fetch request URL.
   * @returns {boolean}
   */
  matchesFetch(fetchUrl) {
    return this.fetchPatterns.some(pattern => fetchUrl.includes(pattern));
  }

  /**
   * Find the input element on the page.
   * @returns {Element|null}
   */
  findInput() {
    for (const sel of this.inputSelectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  /**
   * Find the submit button on the page.
   * @returns {Element|null}
   */
  findSubmitButton() {
    for (const sel of this.submitSelectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  /**
   * Find the last assistant response element.
   * @returns {Element|null}
   */
  findLastResponse() {
    if (!this.responseSelector) return null;
    const all = document.querySelectorAll(this.responseSelector);
    return all.length > 0 ? all[all.length - 1] : null;
  }

  /**
   * Check if the chatbot is currently streaming a response.
   * @returns {boolean}
   */
  isStreaming() {
    if (!this.streamingIndicator) return false;
    return document.querySelector(this.streamingIndicator) !== null;
  }
}

// ─── Provider Registry ────────────────────────────────────────────

/** @type {Map<string, BaseAdapter>} */
const registry = new Map();

/**
 * Register a provider adapter.
 * @param {BaseAdapter} adapter - Adapter instance to register.
 */
export function registerAdapter(adapter) {
  registry.set(adapter.key, adapter);
}

/**
 * Get an adapter by its key.
 * @param {string} key - Provider key.
 * @returns {BaseAdapter|undefined}
 */
export function getAdapter(key) {
  return registry.get(key);
}

/**
 * Find the adapter that matches a given page URL.
 * @param {string} url - The page URL.
 * @returns {BaseAdapter|undefined}
 */
export function getAdapterForUrl(url) {
  for (const adapter of registry.values()) {
    if (adapter.matchesUrl(url)) return adapter;
  }
  return undefined;
}

/**
 * Find the adapter whose fetch patterns match a given API URL.
 * @param {string} fetchUrl - The fetch request URL.
 * @returns {BaseAdapter|undefined}
 */
export function getAdapterForFetch(fetchUrl) {
  for (const adapter of registry.values()) {
    if (adapter.matchesFetch(fetchUrl)) return adapter;
  }
  return undefined;
}

/**
 * Get all registered adapters.
 * @returns {BaseAdapter[]}
 */
export function getAllAdapters() {
  return [...registry.values()];
}

/**
 * Get all registered provider keys.
 * @returns {string[]}
 */
export function getAllProviderKeys() {
  return [...registry.keys()];
}
