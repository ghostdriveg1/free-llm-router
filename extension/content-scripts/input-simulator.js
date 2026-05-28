/**
 * @fileoverview Input simulation content script (ISOLATED world).
 * Simulates human-like typing and prompt submission on chatbot pages.
 */

(function () {
  'use strict';

  // Box-Muller transform for Gaussian typing delays
  function gaussianRandom(mean, stdDev) {
    let u1 = 0, u2 = 0;
    while (u1 === 0) u1 = Math.random();
    while (u2 === 0) u2 = Math.random();
    const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
    return mean + z * stdDev;
  }

  function getCharDelay(char) {
    let mean = 90;
    let stdDev = 25;

    if (char === ' ') {
      mean = 65;
      stdDev = 15;
    } else if (/[.!?\n]/.test(char)) {
      mean = 180;
      stdDev = 50;
    } else if (/[A-Z]/.test(char)) {
      mean = 110;
      stdDev = 30;
    }

    const delay = gaussianRandom(mean, stdDev);
    const clamped = Math.max(30, Math.min(300, delay));

    // 8% chance of a thinking pause
    if (Math.random() < 0.08) {
      const pause = 250 + Math.random() * 500;
      return Math.round(clamped + pause);
    }

    return Math.round(clamped);
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /**
   * Human-like typing simulation into an HTML element.
   * Works on textarea and ProseMirror contenteditable elements.
   */
  async function typePrompt(element, text) {
    if (!element) throw new Error('Target input element not found.');

    element.focus();
    await sleep(200);

    // Load typingMode from storage state
    let typingMode = 'standard';
    try {
      const storageData = await new Promise((resolve) => {
        chrome.storage.local.get(['typingMode'], resolve);
      });
      if (storageData && storageData.typingMode) {
        typingMode = storageData.typingMode;
      }
    } catch (err) {
      console.warn('[Nancy/Simulator] Failed to load typingMode:', err);
    }

    // Clear existing text if any
    if (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT') {
      element.value = '';
    } else if (element.getAttribute('contenteditable') === 'true') {
      element.innerHTML = '';
    }

    element.dispatchEvent(new Event('focus', { bubbles: true }));

    if (typingMode === 'fast') {
      console.log('[Nancy/Simulator] Fast Mode active. Injecting text instantly.');
      if (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT') {
        element.value = text;
      } else if (element.getAttribute('contenteditable') === 'true') {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(element);
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand('insertText', false, text);
      }
      
      // Dispatch final react/vue updating state events
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(150);
      return;
    }

    for (let i = 0; i < text.length; i++) {
      const char = text[i];

      // Create Keyboard events
      const keydownEvent = new KeyboardEvent('keydown', {
        key: char,
        code: `Key${char.toUpperCase()}`,
        bubbles: true,
        cancelable: true,
      });
      element.dispatchEvent(keydownEvent);

      // Insert character
      if (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT') {
        element.value += char;
      } else if (element.getAttribute('contenteditable') === 'true') {
        // Safe document.execCommand for rich text editors
        document.execCommand('insertText', false, char);
      }

      // Input event to trigger internal React/Vue state updates
      const inputEvent = new Event('input', { bubbles: true });
      element.dispatchEvent(inputEvent);

      const keyupEvent = new KeyboardEvent('keyup', {
        key: char,
        code: `Key${char.toUpperCase()}`,
        bubbles: true,
        cancelable: true,
      });
      element.dispatchEvent(keyupEvent);

      // Human-like typing cadence delay
      await sleep(getCharDelay(char));
    }

    // Trigger blur/change events to finalize react state updates
    element.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(100);
  }

  // Export to global scope
  window.NancyInputSimulator = {
    typePrompt,
    sleep,
  };
})();
