/**
 * @fileoverview Side Panel Dashboard Logic.
 * Manages configuration form, listens to state changes in chrome.storage,
 * repaints active tasks and provider status indicators, and displays console logs.
 */

import * as storage from '../utils/storage.js';

// DOM Elements
const statusBadge = document.getElementById('connection-status-badge');
const healthyProvidersCount = document.getElementById('healthy-providers-count');
const providersList = document.getElementById('providers-list');
const activeTasksCount = document.getElementById('active-tasks-count');
const taskQueueBody = document.getElementById('task-queue-body');
const formHfUrl = document.getElementById('input-hf-url');
const formApiKey = document.getElementById('input-api-key');
const formSettings = document.getElementById('settings-form');
const btnReconnect = document.getElementById('btn-reconnect');
const btnClearLogs = document.getElementById('btn-clear-logs');
const consoleLogsBox = document.getElementById('console-logs');
const formTypingMode = document.getElementById('select-typing-mode');

// ─── Initial Page Load ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  await repaintUI();
  
  // Periodically repaint just in case
  setInterval(repaintUI, 2000);
});

async function loadConfig() {
  const state = await storage.getState();
  formHfUrl.value = state.hfSpaceUrl || 'http://127.0.0.1:7860';
  formApiKey.value = state.apiKey || '';
  formTypingMode.value = state.typingMode || 'standard';
}

// ─── UI Render Functions ─────────────────────────────────────────────────────
async function repaintUI() {
  const state = await storage.getState();

  // 1. Repaint Connection Status
  if (state.connected) {
    statusBadge.className = 'connection-status connected';
    statusBadge.querySelector('.status-text').innerText = 'Connected';
  } else {
    statusBadge.className = 'connection-status';
    statusBadge.querySelector('.status-text').innerText = 'Disconnected';
  }

  // 2. Repaint Providers Grid
  let activeProviders = 0;
  const providerKeys = Object.keys(state.providers);
  
  providerKeys.forEach(key => {
    const pState = state.providers[key];
    const card = providersList.querySelector(`[data-provider="${key}"]`);
    if (card) {
      const indicator = card.querySelector('.provider-indicator');
      indicator.className = `provider-indicator ${pState.status}`;
      
      if (pState.status === 'healthy') {
        activeProviders++;
      }
    }
  });

  healthyProvidersCount.innerText = `${activeProviders}/${providerKeys.length} Healthy`;

  // 3. Repaint Active Tasks Table
  const activeTasks = state.taskQueue || [];
  activeTasksCount.innerText = `${activeTasks.length} Active`;

  if (activeTasks.length === 0) {
    taskQueueBody.innerHTML = `
      <tr class="empty-state">
        <td colspan="3">No active relay tasks.</td>
      </tr>
    `;
  } else {
    taskQueueBody.innerHTML = activeTasks.map(task => {
      const displayId = task.taskId.substring(0, 8);
      const providerName = task.provider.charAt(0).toUpperCase() + task.provider.slice(1);
      return `
        <tr>
          <td style="font-family: monospace; font-weight: 500; color: var(--color-primary);">${displayId}</td>
          <td>${providerName}</td>
          <td><span class="task-status ${task.status}">${task.status}</span></td>
        </tr>
      `;
    }).join('');
  }

  // 4. Repaint Console Logs
  const logs = state.logs || [];
  consoleLogsBox.innerHTML = logs.map(entry => {
    const timeStr = new Date(entry.ts).toLocaleTimeString();
    return `
      <div class="log-entry ${entry.level}">
        <span class="log-time">[${timeStr}]</span>
        <span class="log-level">${entry.level}:</span>
        <span class="log-text">${escapeHtml(entry.message)}</span>
      </div>
    `;
  }).join('');
  
  // Auto-scroll to bottom of logs
  consoleLogsBox.scrollTop = consoleLogsBox.scrollHeight;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ─── Settings Form & Actions ─────────────────────────────────────────────────
formSettings.addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const hfSpaceUrl = formHfUrl.value.trim();
  const apiKey = formApiKey.value.trim();
  const typingMode = formTypingMode.value;

  await storage.setState({ hfSpaceUrl, apiKey, typingMode });
  await storage.appendLog('info', `Configuration saved. Typing Mode set to: ${typingMode}. Reconnecting...`);
  
  // Force a service-worker reconnect trigger
  chrome.runtime.sendMessage({ type: 'FORCE_RECONNECT' });
  
  await repaintUI();
});

btnReconnect.addEventListener('click', async () => {
  await storage.appendLog('info', 'Manual reconnect triggered by user.');
  chrome.runtime.sendMessage({ type: 'FORCE_RECONNECT' });
});

btnClearLogs.addEventListener('click', async () => {
  await storage.setState({ logs: [] });
  await repaintUI();
});

// "Open Tab" Click Delegation
providersList.addEventListener('click', (e) => {
  const btn = e.target.closest('.btn-open-tab');
  if (!btn) return;

  const provider = btn.getAttribute('data-provider');
  const urls = {
    chatgpt: 'https://chatgpt.com',
    gemini: 'https://gemini.google.com',
    deepseek: 'https://chat.deepseek.com',
    kimi: 'https://kimi.moonshot.cn',
    claude: 'https://claude.ai',
  };

  if (urls[provider]) {
    chrome.tabs.create({ url: urls[provider], active: true });
  }
});

// Listen to storage changes from service worker for instant UI updates
chrome.storage.onChanged.addListener(async () => {
  await repaintUI();
});
