/**
 * @fileoverview Central background service worker for Nancy Chrome Extension.
 * Coordinates connection with Nancy HF Space server, handles task routing,
 * manages tab lifecycle, and relays response chunks back to the server.
 * @module service-worker
 */

import { getAdapter } from './adapters/base.js';
import './adapters/chatgpt.js'; // Registers ChatGPT adapter
import './adapters/gemini.js';  // Registers Gemini adapter
import './adapters/deepseek.js';// Registers DeepSeek adapter
import './adapters/kimi.js';    // Registers Kimi adapter
import './adapters/claude.js';  // Registers Claude adapter
import './adapters/nim.js';     // Registers NVIDIA NIM Portal adapter
import './adapters/zai.js';     // Registers z.ai adapter
import * as storage from './utils/storage.js';
import { SSEParser } from './utils/sse-parser.js';
import { sleep } from './utils/timing.js';

// ─── Stable Extension ID (survives service worker restarts) ────────────────
// Generated once and persisted to storage. If Chrome kills and restarts the
// worker, we reconnect to Nancy with the same ID so in-flight tasks are not lost.
let EXTENSION_ID = 'nancy-extension-pending';
let activeReader = null;
let reconnectTimer = null;
let currentTaskMap = new Map(); // task_id -> { providerKey, tabId }

async function getOrCreateExtensionId() {
  const stored = await new Promise(resolve => chrome.storage.local.get('extensionId', resolve));
  if (stored.extensionId) {
    EXTENSION_ID = stored.extensionId;
  } else {
    EXTENSION_ID = 'nancy-extension-' + Math.random().toString(36).substr(2, 9);
    await chrome.storage.local.set({ extensionId: EXTENSION_ID });
  }
  return EXTENSION_ID;
}

// ─── Real-Time Open Tab Discovery & Health Sync ──────────────────────────────
async function scanOpenTabs() {
  try {
    const state = await storage.getState();
    const tabs = await chrome.tabs.query({});
    const providerKeys = Object.keys(state.providers);
    
    for (const key of providerKeys) {
      const adapter = getAdapter(key);
      if (!adapter) continue;
      
      const matchedTab = tabs.find(t => t.url && adapter.matchesUrl(t.url));
      const current = state.providers[key];
      
      if (matchedTab) {
        if (current.status !== 'healthy' || current.tabId !== matchedTab.id) {
          await storage.updateProvider(key, { tabId: matchedTab.id, status: 'healthy' });
          await storage.appendLog('info', `Detected active tab for ${adapter.name} (Tab ID: ${matchedTab.id}). Marked as Healthy.`);
        }
      } else {
        if (current.status !== 'offline') {
          await storage.updateProvider(key, { tabId: -1, status: 'offline' });
          await storage.appendLog('info', `${adapter.name} tab closed or not found. Marked as Offline.`);
        }
      }
    }
  } catch (err) {
    console.error('[Nancy/SW] Error scanning open tabs:', err);
  }
}

// Bind tab lifecycle listeners for real-time reactivity
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' || changeInfo.url) {
    scanOpenTabs();
  }
});
chrome.tabs.onRemoved.addListener(() => {
  scanOpenTabs();
});

// ─── Startup Hook ───────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(async () => {
  await getOrCreateExtensionId();
  await storage.resetState();
  await storage.appendLog('info', `Nancy installed. Extension ID: ${EXTENSION_ID}`);
  
  // Enable opening side panel when clicking the extension icon
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
  
  setupAlarms();
  connectToServer();
  await scanOpenTabs();
});

chrome.runtime.onStartup.addListener(async () => {
  await getOrCreateExtensionId();
  await storage.appendLog('info', 'Nancy service worker started.');

  // ── URL Migration: update old default HF Space URL to local dev URL ──
  const currentState = await storage.getState();
  const OLD_DEFAULT = 'https://nancy.hf.space';
  const NEW_DEFAULT = 'http://127.0.0.1:7860';
  if (currentState.hfSpaceUrl === OLD_DEFAULT) {
    await storage.setState({ hfSpaceUrl: NEW_DEFAULT });
    await storage.appendLog('info', `URL migrated from ${OLD_DEFAULT} → ${NEW_DEFAULT}`);
  }
  // ────────────────────────────────────────────────────────────────────
  
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
  
  setupAlarms();
  connectToServer();
  await scanOpenTabs();
});

// ─── Alarms & Keep-Alive ─────────────────────────────────────────────────────
function setupAlarms() {
  // Alarms keep the worker alive and schedule periodic heartbeats
  chrome.alarms.clearAll(() => {
    chrome.alarms.create('heartbeat', { periodInMinutes: 0.4 }); // Every ~24s
    chrome.alarms.create('connection_check', { periodInMinutes: 1.0 }); // Every 60s
  });
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'heartbeat') {
    await sendHeartbeat();
    await scanOpenTabs();
  } else if (alarm.name === 'connection_check') {
    const state = await storage.getState();
    if (!state.connected) {
      await storage.appendLog('warn', 'Connection check: offline. Reconnecting...');
      connectToServer();
    }
    await scanOpenTabs();
  }
});

// ─── SSE Streaming Connection ────────────────────────────────────────────────
async function connectToServer() {
  // Ensure stable ID is loaded (worker may be woken by alarm before startup fires)
  if (EXTENSION_ID === 'nancy-extension-pending') {
    await getOrCreateExtensionId();
  }

  if (activeReader) {
    try {
      await activeReader.cancel();
    } catch {}
    activeReader = null;
  }

  const state = await storage.getState();
  const url = state.hfSpaceUrl;
  const key = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5'; // Fallback to extension secret

  if (!url) {
    await storage.appendLog('error', 'Nancy Server URL not configured.');
    return;
  }

  await storage.appendLog('info', `Connecting to Nancy server at ${url}...`);
  await storage.setState({ connected: false });

  const streamUrl = `${url.replace(/\/$/, '')}/ext/tasks/stream?extension_id=${EXTENSION_ID}`;
  const sseParser = new SSEParser();

  try {
    const response = await fetch(streamUrl, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${key}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}: ${response.statusText}`);
    }

    await storage.setState({ connected: true });
    await storage.appendLog('info', 'SSE connection established successfully.');

    const reader = response.body.getReader();
    activeReader = reader;
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        await storage.appendLog('info', 'SSE connection closed by server.');
        break;
      }

      const chunkText = decoder.decode(value, { stream: true });
      const events = sseParser.feed(chunkText);

      for (const event of events) {
        if (event.event === 'task') {
          try {
            const task = JSON.parse(event.data);
            await storage.appendLog('info', `Received task ${task.task_id} for ${task.provider}`);
            // Fire-and-forget task execution
            executeTask(task);
          } catch (e) {
            await storage.appendLog('error', `Failed to parse task: ${e.message}`);
          }
        } else if (event.event === 'ping') {
          // Keep-alive heartbeat acknowledgement
          await storage.updateProvider('chatgpt', { lastSeen: Date.now() });
        }
      }
    }
  } catch (err) {
    await storage.setState({ connected: false });
    await storage.appendLog('error', `SSE connection error: ${err.message}`);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    connectToServer();
  }, 10000); // Reconnect after 10 seconds
}

// ─── Heartbeat ───────────────────────────────────────────────────────────────
async function sendHeartbeat() {
  const state = await storage.getState();
  if (!state.hfSpaceUrl) return;

  const secret = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5';
  const url = `${state.hfSpaceUrl.replace(/\/$/, '')}/ext/heartbeat`;

  try {
    const activeTasks = Array.from(currentTaskMap.keys());
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        extension_id: EXTENSION_ID,
        timestamp: Date.now() / 1000,
        active_tasks: activeTasks,
      }),
    });

    if (response.ok) {
      const result = await response.json();
      logger(`Heartbeat ok: ${result.status}`);
    } else {
      logger(`Heartbeat failed: HTTP ${response.status}`);
    }
  } catch (err) {
    logger(`Heartbeat catch: ${err.message}`);
  }
}

function logger(msg) {
  console.log(`[Nancy/SW] ${msg}`);
}

// ─── Task Execution Lifecycle ────────────────────────────────────────────────
function formatMessageHistory(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return '';
  if (messages.length === 1) {
    return messages[0].content || '';
  }
  
  let formatted = "Below is the full conversation history and context. Please respond to the last user message as the assistant:\n\n";
  messages.forEach((msg) => {
    const role = msg.role.toUpperCase();
    const content = msg.content || '';
    formatted += `[${role}]: ${content}\n\n`;
  });
  formatted += "Please generate your response as the assistant now:";
  return formatted;
}

async function executeTask(task) {
  const { task_id, provider, messages, action, conversation_url, session_id } = task;
  const fullPrompt = formatMessageHistory(messages);

  if (!fullPrompt) {
    await reportError(task_id, 'No message content found in task payload.');
    return;
  }

  // Persist task state in local storage
  await storage.enqueueTask({
    taskId: task_id,
    provider: provider,
    status: 'pending',
    prompt: fullPrompt.length > 60 ? fullPrompt.substr(0, 57) + '...' : fullPrompt,
    created: Date.now(),
  });

  try {
    let tab;

    // ── Session-aware tab navigation ──────────────────────────────────
    if (action === 'new_chat') {
      // Force a fresh conversation by navigating to the provider's base URL
      const adapter = getAdapter(provider);
      if (!adapter) throw new Error(`Provider adapter '${provider}' is not supported.`);
      const baseUrl = `https://${adapter.urlPatterns[0]}`;
      const existingTabs = await chrome.tabs.query({});
      const matchedTab = existingTabs.find(t => t.url && adapter.matchesUrl(t.url));
      if (matchedTab) {
        // Navigate existing tab to the root (starts a new chat)
        await chrome.tabs.update(matchedTab.id, { url: baseUrl, active: true });
        tab = matchedTab;
        await waitTabLoaded(tab.id);
        await sleep(3000); // Wait for the new chat interface to initialize
      } else {
        tab = await getOrCreateProviderTab(provider);
      }
      await storage.appendLog('info', `Session action 'new_chat' — navigated to ${baseUrl}`);

    } else if (action === 'resume_chat' && conversation_url) {
      // Navigate directly to a specific saved conversation URL
      const existingTabs = await chrome.tabs.query({});
      const adapter = getAdapter(provider);
      const matchedTab = existingTabs.find(t => t.url && adapter && adapter.matchesUrl(t.url));
      if (matchedTab) {
        await chrome.tabs.update(matchedTab.id, { url: conversation_url, active: true });
        tab = matchedTab;
        await waitTabLoaded(tab.id);
        await sleep(3000); // Wait for the conversation to load
      } else {
        // Open a new tab directly to the conversation URL
        tab = await chrome.tabs.create({ url: conversation_url, active: true });
        await waitTabLoaded(tab.id);
        await sleep(3500);
      }
      await storage.appendLog('info', `Session action 'resume_chat' — navigated to ${conversation_url}`);

    } else {
      // Default 'continue': find or create the provider tab as normal
      tab = await getOrCreateProviderTab(provider);
    }

    currentTaskMap.set(task_id, { providerKey: provider, tabId: tab.id, session_id });
    await storage.updateTask(task_id, { status: 'typing' });

    // Give Chrome a short pause to awaken the tab and ensure content scripts are active
    await sleep(1500);

    // Inject and send prompting command to content script
    try {
      await chrome.tabs.sendMessage(tab.id, {
        type: 'SUBMIT_PROMPT',
        taskId: task_id,
        prompt: fullPrompt,
        provider: provider,
      });
    } catch (sendErr) {
      if (sendErr.message && sendErr.message.includes('Receiving end does not exist')) {
        await storage.appendLog('warn', `Content script inactive on tab ${tab.id}. Triggering self-healing reload...`);

        // Reload the tab programmatically
        await chrome.tabs.reload(tab.id);
        await waitTabLoaded(tab.id);

        // Wait 3.5 seconds for all content scripts to fully inject and initialize
        await sleep(3500);

        // Retry sending the prompting command
        await chrome.tabs.sendMessage(tab.id, {
          type: 'SUBMIT_PROMPT',
          taskId: task_id,
          prompt: fullPrompt,
          provider: provider,
        });
      } else {
        throw sendErr;
      }
    }

  } catch (err) {
    await storage.appendLog('error', `Task ${task_id} failed: ${err.message}`);
    await reportError(task_id, err.message);
  }
}

// ─── Tab Management ──────────────────────────────────────────────────────────
async function getOrCreateProviderTab(providerKey) {
  const adapter = getAdapter(providerKey);
  if (!adapter) {
    throw new Error(`Provider adapter '${providerKey}' is not supported.`);
  }

  const tabs = await chrome.tabs.query({});
  let matchedTab = tabs.find(t => t.url && adapter.matchesUrl(t.url));

  if (matchedTab) {
    // If tab is found, update its tabId reference in local storage
    await storage.updateProvider(providerKey, { tabId: matchedTab.id, status: 'healthy' });
    return matchedTab;
  }

  // Need to open a new tab
  await storage.appendLog('info', `Opening new tab for ${adapter.name}...`);
  const targetUrl = `https://${adapter.urlPatterns[0]}`;
  const newTab = await chrome.tabs.create({ url: targetUrl, active: true });
  
  await storage.updateProvider(providerKey, { tabId: newTab.id, status: 'healthy' });
  await waitTabLoaded(newTab.id);
  
  // Extra pause for JS to initialize in the loaded page
  await sleep(3000);
  return newTab;
}

function waitTabLoaded(tabId) {
  return new Promise((resolve) => {
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    // Safety check
    chrome.tabs.get(tabId, (tab) => {
      if (tab && tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    });
  });
}

// Async POST telemetry back to Nancy Server for central visibility
async function postLogToServer(provider, level, messageText) {
  const state = await storage.getState();
  if (!state.hfSpaceUrl) return;

  const secret = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5';
  const url = `${state.hfSpaceUrl.replace(/\/$/, '')}/ext/log`;

  try {
    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        extension_id: EXTENSION_ID,
        level: level,
        provider: provider || 'system',
        message: messageText,
      }),
    });
  } catch (err) {
    // Silent catch to prevent fetch-level loops
  }
}

// ─── Messaging & Responses ───────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const { type, taskId, chunk, error, provider } = message;

  if (type === 'CHUNK') {
    handleResponseChunk(taskId, chunk);
  } else if (type === 'COMPLETE') {
    handleTaskComplete(taskId);
  } else if (type === 'ERROR') {
    handleTaskError(taskId, error);
  } else if (type === 'TAB_LOG') {
    storage.appendLog('info', `[${provider}] ${message.message}`);
    postLogToServer(provider, 'info', message.message).catch(() => {});
  } else if (type === 'FORCE_RECONNECT') {
    connectToServer();
  }

  // Keep message channel open for async responses
  return true;
});

async function handleResponseChunk(taskId, chunk) {
  await storage.updateTask(taskId, { status: 'streaming' });
  const state = await storage.getState();
  if (!state.hfSpaceUrl) return;

  const secret = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5';
  const url = `${state.hfSpaceUrl.replace(/\/$/, '')}/ext/response`;

  try {
    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        task_id: taskId,
        chunk: chunk,
        is_done: false,
      }),
    });
  } catch (err) {
    logger(`Failed to relay chunk: ${err.message}`);
  }
}

async function handleTaskComplete(taskId) {
  await storage.updateTask(taskId, { status: 'done' });
  setTimeout(() => storage.removeTask(taskId), 5000); // Auto remove after 5s

  const state = await storage.getState();
  if (!state.hfSpaceUrl) return;

  const secret = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5';
  const url = `${state.hfSpaceUrl.replace(/\/$/, '')}/ext/response`;

  // Capture current tab URL for session persistence
  let conversationUrl = null;
  const taskMeta = currentTaskMap.get(taskId);
  if (taskMeta && taskMeta.tabId) {
    try {
      const tab = await chrome.tabs.get(taskMeta.tabId);
      conversationUrl = tab?.url || null;
    } catch {
      // Tab might have been closed — not critical
    }
  }

  try {
    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        task_id: taskId,
        chunk: '',
        is_done: true,
        conversation_url: conversationUrl, // Report back for session persistence
      }),
    });
    await storage.appendLog('info', `Task ${taskId} completed. URL: ${conversationUrl || 'unknown'}`);
  } catch (err) {
    logger(`Failed to complete task on server: ${err.message}`);
  } finally {
    currentTaskMap.delete(taskId);
  }
}


async function handleTaskError(taskId, errorMsg) {
  await storage.updateTask(taskId, { status: 'error' });
  await storage.appendLog('error', `Task ${taskId} error: ${errorMsg}`);
  await reportError(taskId, errorMsg);
}

async function reportError(taskId, errorMsg) {
  const state = await storage.getState();
  if (!state.hfSpaceUrl) return;

  const secret = state.apiKey || 'nancy_ext_sec_8d4f0b21a3672d9e18b5';
  const url = `${state.hfSpaceUrl.replace(/\/$/, '')}/ext/response`;

  try {
    await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        task_id: taskId,
        error: errorMsg,
        is_done: false,
      }),
    });
  } catch (err) {
    logger(`Failed to send error state: ${err.message}`);
  } finally {
    currentTaskMap.delete(taskId);
    setTimeout(() => storage.removeTask(taskId), 10000); // Clear from UI in 10s
  }
}
