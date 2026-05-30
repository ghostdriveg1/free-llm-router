/**
 * @fileoverview DOM Observer content script (ISOLATED world).
 * Orchestrates:
 *  - Finding page input & submit fields
 *  - Triggering input-simulator typing
 *  - Observing responses via SSE postMessage bridge (Primary) or MutationObserver delta scraping (Fallback)
 */

(function () {
  'use strict';

  let currentTaskId = null;
  let currentProvider = null;
  let activeObserver = null;
  let lastResponseLength = 0;
  let completionTimeout = null;

  const PROVIDERS = {
    chatgpt: {
      name: 'ChatGPT',
      input: ['#prompt-textarea', 'div[contenteditable="true"][id="prompt-textarea"]', 'div[contenteditable="true"]', '[contenteditable="true"]'],
      submit: [
        'button[data-testid="send-button"]',
        'button[data-testid="fruitjuice-send-button"]',
        'button[aria-label="Send prompt"]',
        'button[aria-label="Send message"]',
        '#composer-background button[aria-label]',
        'button[class*="send"]',
      ],
      response: '[data-message-author-role="assistant"]',
      streaming: '.result-streaming, [class*="result-streaming"], button[aria-label="Stop generating"], button[data-testid="stop-button"]',
    },
    gemini: {
      name: 'Gemini',
      input: [
        'div.ql-editor[contenteditable="true"]',
        'div[contenteditable="true"][aria-label="Enter a prompt here"]',
        'div[contenteditable="true"][aria-label="Prompt"]',
        'rich-textarea div[contenteditable="true"]',
        'textarea',
        '[contenteditable="true"]',
      ],
      submit: [
        'button.send-button[aria-label]',
        'button[aria-label="Send message"]',
        'button[aria-label="Submit"]',
        'button[class*="send"]',
        'div[aria-label="Send message"] button',
        'mat-icon-button[aria-label*="send"]',
      ],
      response: 'model-response .markdown, model-response, .model-response-text, [class*="model-response"], message-content',
      streaming: 'model-response.generating, .loading-indicator, [class*="generating"], mat-progress-spinner',
    },
    deepseek: {
      name: 'DeepSeek',
      input: ['#chat-input-textarea', 'textarea', '#chat-input', '[contenteditable="true"]'],
      submit: ['button[aria-label="Send message"]', 'div[class*="send-button"]', 'button[class*="send"]', '[class*="send-button"]', '[class*="sendButton"]', '[class*="send"]'],
      response: 'div[class*="assistant-message"]',
      streaming: 'div[class*="streaming"], div[class*="loading"]',
    },
    kimi: {
      name: 'Kimi',
      input: ['div.chat-input-editor[contenteditable="true"]', '#kimi-chat-input', 'div[contenteditable="true"]', 'textarea', '[contenteditable="true"]'],
      submit: ['button[aria-label*="发送"]', 'button[aria-label*="Send"]', 'button[class*="send"]', '[class*="send-button"]', 'button[type="submit"]', '[class*="send"]'],
      response: 'div[class*="assistant"]',
      streaming: '.streaming-indicator, [class*="streaming"]',
    },
    claude: {
      name: 'Claude',
      input: ['[contenteditable="true"]', 'textarea'],
      submit: ['button[aria-label="Send Message"]', 'button[class*="send"]'],
      response: 'div[class*="assistant-message"]',
      streaming: '.generating, [class*="generating"]',
    },
    nim: {
      name: 'NVIDIA NIM',
      input: ['textarea[placeholder*="message"]', 'textarea[placeholder*="Message"]', 'textarea[data-testid="chat-input"]', 'textarea'],
      submit: ['button[aria-label="Send"]', 'button[aria-label="Send message"]', 'button[type="submit"]', 'form button:last-child'],
      response: 'div[data-role="assistant"], div[class*="assistant"], div[class*="message"][class*="response"]',
      streaming: '[class*="streaming"], [class*="loading"], [class*="generating"]',
    },
    zai: {
      name: 'z.ai',
      input: ['div[contenteditable="true"][data-placeholder]', 'div[contenteditable="true"]', 'textarea'],
      submit: ['button[aria-label="Send"]', 'button[aria-label="Send message"]', 'button[class*="send"]', 'button[type="submit"]'],
      response: 'div[data-role="assistant"], div[class*="assistant-message"], div[class*="ai-message"], div[class*="bot-message"]',
      streaming: '[class*="streaming"], [class*="loading"], [class*="typing"]',
    },
  };

  function detectProvider() {
    const host = window.location.hostname;
    if (host.includes('openai.com') || host.includes('chatgpt.com')) return 'chatgpt';
    if (host.includes('gemini.google.com') || host.includes('gemini.google')) return 'gemini';
    if (host.includes('deepseek.com')) return 'deepseek';
    if (host.includes('kimi.moonshot.cn') || host.includes('kimi.ai') || host.includes('kimi.com')) return 'kimi';
    if (host.includes('claude.ai')) return 'claude';
    if (host.includes('build.nvidia.com') || host.includes('nim.developer.nvidia.com')) return 'nim';
    if (host.includes('z.ai') || host.includes('chat.z.ai')) return 'zai';
    return null;
  }

  function getSelectors(providerKey) {
    return PROVIDERS[providerKey || detectProvider()];
  }

  function findElement(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function log(msg) {
    chrome.runtime.sendMessage({
      type: 'TAB_LOG',
      provider: currentProvider || detectProvider() || 'unknown',
      message: msg,
    });
  }

  // ─── PostMessage bridge (Primary - SSE interception) ────────────────────────
  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'NANCY_CHUNK') {
      const { chunk, taskId } = event.data;
      if (taskId === currentTaskId) {
        // Clear DOM fallback completion timeouts
        if (completionTimeout) clearTimeout(completionTimeout);
        
        chrome.runtime.sendMessage({
          type: 'CHUNK',
          taskId: taskId,
          chunk: chunk,
        });

        // Trigger done signal if main-interceptor flags it
        if (event.data.isDone) {
          log('SSE stream completion intercepted.');
          chrome.runtime.sendMessage({
            type: 'COMPLETE',
            taskId: taskId,
          });
          cleanupTaskState();
        }
      }
    }
  });

  // ─── Service Worker Command Listener ───────────────────────────────────────
  chrome.runtime.onMessage.addListener(async (message, sender, sendResponse) => {
    if (message.type === 'SUBMIT_PROMPT') {
      const { taskId, prompt, provider } = message;
      currentTaskId = taskId;
      currentProvider = provider;
      lastResponseLength = 0;

      log(`Beginning prompt simulation. TaskId: ${taskId}`);

      try {
        const config = getSelectors(provider);
        if (!config) throw new Error(`Provider config not found for ${provider}`);

        const inputEl = findElement(config.input);
        if (!inputEl) throw new Error(`Could not locate prompt input element.`);

        // 1. Notify main-interceptor of the active taskId
        window.postMessage({ type: 'NANCY_SET_TASK_ID', taskId }, '*');

        // 2. Human typing simulation
        await window.NancyInputSimulator.typePrompt(inputEl, prompt);
        log('Keystroke simulation complete.');

        // 3. Locate and click submit button.
        // After fast-mode injection, React/ProseMirror needs time to process
        // the new content and enable the send button. Poll for up to 1.5 seconds.
        let submitBtn = null;
        let submitted = false;
        const BUTTON_POLL_MS = 100;
        const BUTTON_POLL_ATTEMPTS = 15; // 15 × 100ms = 1.5 seconds

        for (let attempt = 0; attempt < BUTTON_POLL_ATTEMPTS; attempt++) {
          await window.NancyInputSimulator.sleep(BUTTON_POLL_MS);
          submitBtn = findElement(config.submit);
          if (submitBtn && !submitBtn.disabled && submitBtn.getAttribute('aria-disabled') !== 'true') {
            submitBtn.click();
            log('Send button clicked (attempt ' + (attempt + 1) + ').');
            submitted = true;
            break;
          }
        }

        if (!submitted) {
          log('Submit button not found or still disabled after 1.5s. Trying Enter key fallback...');
        }

        // 4. Enter-key fallback
        if (!submitted) {
          log('Simulating Enter keypress event to submit...');
          inputEl.focus();
          const enterEvent = new KeyboardEvent('keydown', {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true,
          });
          inputEl.dispatchEvent(enterEvent);
          inputEl.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          inputEl.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
          log('Enter keypress events dispatched.');
        }

        // 5. Start DOM observer fallback
        startDOMObserver(config);

      } catch (err) {
        log(`Error: ${err.message}`);
        chrome.runtime.sendMessage({
          type: 'ERROR',
          taskId: taskId,
          error: err.message,
        });
        cleanupTaskState();
      }
    }
    return true;
  });

  // ─── Fallback DOM Mutation Observer ─────────────────────────────────────────
  function startDOMObserver(config) {
    if (activeObserver) activeObserver.disconnect();
    if (completionTimeout) clearTimeout(completionTimeout);

    const observer = new MutationObserver(() => {
      handleDOMMutation(config);
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    activeObserver = observer;
    log('DOM MutationObserver fallback active.');

    // Schedule safety completion timeout (if no activity for 20 seconds)
    resetCompletionTimeout();
  }

  function handleDOMMutation(config) {
    const allResponses = document.querySelectorAll(config.response);
    if (allResponses.length === 0) return;

    const lastResponse = allResponses[allResponses.length - 1];
    
    // Extract innerText from markdown node or container
    const markdownNode = lastResponse.querySelector('.markdown, [class*="markdown"]') || lastResponse;
    const currentText = markdownNode.innerText || markdownNode.textContent || '';
    
    const delta = currentText.substr(lastResponseLength);
    
    if (delta.length > 0) {
      resetCompletionTimeout();

      // Send chunk delta
      chrome.runtime.sendMessage({
        type: 'CHUNK',
        taskId: currentTaskId,
        chunk: delta,
      });

      lastResponseLength = currentText.length;
    }

    // Check if streaming indicator has disappeared
    const isStreamingActive = document.querySelector(config.streaming) !== null;
    if (!isStreamingActive && lastResponseLength > 0) {
      // Debounce complete to allow DOM state to settle
      if (completionTimeout) clearTimeout(completionTimeout);
      completionTimeout = setTimeout(() => {
        log('DOM observation complete (class settled).');
        chrome.runtime.sendMessage({
          type: 'COMPLETE',
          taskId: currentTaskId,
        });
        cleanupTaskState();
      }, 1000);
    }
  }

  function resetCompletionTimeout() {
    if (completionTimeout) clearTimeout(completionTimeout);
    completionTimeout = setTimeout(() => {
      log('DOM observation complete (inactivity timeout).');
      chrome.runtime.sendMessage({
        type: 'COMPLETE',
        taskId: currentTaskId,
      });
      cleanupTaskState();
    }, 30000); // 30 seconds of no changes -> complete (was 20s)
  }

  function cleanupTaskState() {
    if (activeObserver) {
      activeObserver.disconnect();
      activeObserver = null;
    }
    if (completionTimeout) {
      clearTimeout(completionTimeout);
      completionTimeout = null;
    }
    currentTaskId = null;
    lastResponseLength = 0;
  }
})();
