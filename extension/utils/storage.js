/**
 * @fileoverview Typed wrappers around chrome.storage.local for
 * persisting extension state across service worker restarts.
 * @module utils/storage
 */

/**
 * @typedef {Object} NancyState
 * @property {string}  hfSpaceUrl   - Base URL of the Nancy HF Space.
 * @property {string}  apiKey       - API key for HF Space authentication.
 * @property {boolean} connected    - Whether SSE connection is active.
 * @property {string}  lastEventId  - Last SSE event ID for reconnection.
 * @property {Object<string, ProviderState>} providers - Per-provider state.
 * @property {TaskInfo[]} taskQueue - Current task queue.
 * @property {LogEntry[]} logs      - Recent log entries (capped).
 */

/**
 * @typedef {Object} ProviderState
 * @property {string}  name   - Display name.
 * @property {string}  status - "healthy" | "degraded" | "offline".
 * @property {number}  tabId  - Chrome tab ID, or -1 if unknown.
 * @property {number}  lastSeen - Timestamp of last activity.
 */

/**
 * @typedef {Object} TaskInfo
 * @property {string} taskId   - Unique task identifier.
 * @property {string} provider - Target provider key.
 * @property {string} status   - "pending" | "typing" | "streaming" | "done" | "error".
 * @property {string} prompt   - The prompt text (truncated for display).
 * @property {number} created  - Timestamp when task was received.
 */

/**
 * @typedef {Object} LogEntry
 * @property {number} ts      - Timestamp.
 * @property {string} level   - "info" | "warn" | "error".
 * @property {string} message - Log message.
 */

/** Maximum number of log entries to keep in storage. */
const MAX_LOGS = 200;

/** Default state shape used when storage is empty. */
const DEFAULT_STATE = {
  // For local dev: use http://127.0.0.1:7860
  // For production HF Space: change to https://nancy.hf.space
  hfSpaceUrl: 'http://127.0.0.1:7860',
  apiKey: '',
  typingMode: 'fast', // 'standard' | 'fast'
  connected: false,
  lastEventId: '',
  providers: {
    chatgpt: { name: 'ChatGPT',      status: 'offline', tabId: -1, lastSeen: 0 },
    gemini:  { name: 'Gemini',       status: 'offline', tabId: -1, lastSeen: 0 },
    deepseek:{ name: 'DeepSeek',     status: 'offline', tabId: -1, lastSeen: 0 },
    kimi:    { name: 'Kimi',         status: 'offline', tabId: -1, lastSeen: 0 },
    claude:  { name: 'Claude',       status: 'offline', tabId: -1, lastSeen: 0 },
    nim:     { name: 'NVIDIA NIM',   status: 'offline', tabId: -1, lastSeen: 0 },
    zai:     { name: 'z.ai',         status: 'offline', tabId: -1, lastSeen: 0 },
  },
  taskQueue: [],
  logs: [],
};

/**
 * Get a value from chrome.storage.local with a fallback default.
 * @template T
 * @param {string} key - Storage key.
 * @param {T} defaultValue - Fallback if key doesn't exist.
 * @returns {Promise<T>}
 */
export async function get(key, defaultValue) {
  try {
    const result = await chrome.storage.local.get(key);
    return result[key] !== undefined ? result[key] : defaultValue;
  } catch (err) {
    console.error(`[Nancy/storage] get("${key}") failed:`, err);
    return defaultValue;
  }
}

/**
 * Set one or more key-value pairs in chrome.storage.local.
 * @param {Object} items - Object of key-value pairs to store.
 * @returns {Promise<void>}
 */
export async function set(items) {
  try {
    await chrome.storage.local.set(items);
  } catch (err) {
    console.error('[Nancy/storage] set() failed:', err);
  }
}

/**
 * Atomically read-modify-write a single key.
 * The updater function receives the current value and returns the new value.
 * @template T
 * @param {string} key - Storage key.
 * @param {T} defaultValue - Default if key doesn't exist yet.
 * @param {(current: T) => T} updater - Pure function that returns the new value.
 * @returns {Promise<T>} The new value after update.
 */
export async function update(key, defaultValue, updater) {
  const current = await get(key, defaultValue);
  const next = updater(current);
  await set({ [key]: next });
  return next;
}

/**
 * Load the full Nancy state, merged with defaults for any missing fields.
 * @returns {Promise<NancyState>}
 */
export async function getState() {
  try {
    const keys = Object.keys(DEFAULT_STATE);
    const result = await chrome.storage.local.get(keys);
    /** @type {NancyState} */
    const state = { ...DEFAULT_STATE };
    for (const key of keys) {
      if (result[key] !== undefined) {
        if (key === 'providers') {
          // Deep-merge providers so new providers get defaults
          state.providers = { ...DEFAULT_STATE.providers, ...result[key] };
        } else {
          state[key] = result[key];
        }
      }
    }
    return state;
  } catch (err) {
    console.error('[Nancy/storage] getState() failed:', err);
    return { ...DEFAULT_STATE };
  }
}

/**
 * Persist a partial state update (only provided keys are written).
 * @param {Partial<NancyState>} partial - Fields to update.
 * @returns {Promise<void>}
 */
export async function setState(partial) {
  await set(partial);
}

/**
 * Append a log entry, auto-trimming to MAX_LOGS.
 * @param {"info"|"warn"|"error"} level - Log severity.
 * @param {string} message - Log message.
 * @returns {Promise<void>}
 */
export async function appendLog(level, message) {
  await update('logs', [], (logs) => {
    const entry = { ts: Date.now(), level, message };
    const updated = [...logs, entry];
    // Trim oldest entries if over cap
    return updated.length > MAX_LOGS
      ? updated.slice(updated.length - MAX_LOGS)
      : updated;
  });
}

/**
 * Update a specific provider's state.
 * @param {string} providerKey - e.g. "chatgpt", "gemini".
 * @param {Partial<ProviderState>} partial - Fields to update.
 * @returns {Promise<void>}
 */
export async function updateProvider(providerKey, partial) {
  await update('providers', DEFAULT_STATE.providers, (providers) => {
    const current = providers[providerKey] || DEFAULT_STATE.providers[providerKey] || {
      name: providerKey, status: 'offline', tabId: -1, lastSeen: 0,
    };
    return {
      ...providers,
      [providerKey]: { ...current, ...partial },
    };
  });
}

/**
 * Add a task to the queue.
 * @param {TaskInfo} task - Task to add.
 * @returns {Promise<void>}
 */
export async function enqueueTask(task) {
  await update('taskQueue', [], (queue) => [...queue, task]);
}

/**
 * Update a task's status in the queue.
 * @param {string} taskId - The task ID to update.
 * @param {Partial<TaskInfo>} partial - Fields to update.
 * @returns {Promise<void>}
 */
export async function updateTask(taskId, partial) {
  await update('taskQueue', [], (queue) =>
    queue.map(t => t.taskId === taskId ? { ...t, ...partial } : t)
  );
}

/**
 * Remove a task from the queue.
 * @param {string} taskId - The task ID to remove.
 * @returns {Promise<void>}
 */
export async function removeTask(taskId) {
  await update('taskQueue', [], (queue) =>
    queue.filter(t => t.taskId !== taskId)
  );
}

/**
 * Clear all stored state and reset to defaults.
 * @returns {Promise<void>}
 */
export async function resetState() {
  await set(DEFAULT_STATE);
}

/**
 * Export the DEFAULT_STATE for reference.
 */
export { DEFAULT_STATE };
