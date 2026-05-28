# Nancy — Troubleshooting & Debugging Guide

This guide details present and potential future bugs across Nancy’s distributed layer (FastAPI orchestrator, Chrome Extension service worker, page content scripts, and Redis integrations) and explains how to debug them step-by-step.

---

## ─── 1. Extension-to-Server SSE Connection Failures ───

### Present/Potential Bug: "SSE connection error: HTTP 401 Unauthorized"
*   **Symptom**: The extension status badge remains grey/disconnected, and logs show `SSE connection error: Server returned HTTP 401: Unauthorized`.
*   **Cause**: The API key (`apiKey`) saved in the extension settings does not match the `NANCY_EXT_SECRET` set in your Hugging Face Space repository secrets.
*   **How to Debug**:
    1.  Open your Hugging Face Space Settings page.
    2.  Check the value of `NANCY_EXT_SECRET`.
    3.  Open the Nancy Chrome Extension side panel, scroll to the **Relay Config** section, and verify that the **Auth Token / API Key** field exactly matches your `NANCY_EXT_SECRET`.
    4.  Click **Save Config** and then **Reconnect**.

### Present/Potential Bug: "Server URL not configured" or "Failed to fetch"
*   **Symptom**: Logs show `Nancy Server URL not configured` or `Failed to fetch`.
*   **Cause**: The space URL is misspelled, has an active block, or is private.
*   **How to Debug**:
    1.  Ensure your Hugging Face Space is set to **Public** visibility (Settings → Danger Zone → Change visibility). Private spaces block direct HTTP requests from Chrome extensions.
    2.  Ensure the URL has the correct format: `https://<your-username>-<your-space-name>.hf.space` (do not include `/v1` or `/ext` paths at the end).

---

## ─── 2. Browser Tab Matching and Waking Issues ───

### Present/Potential Bug: "Could not establish connection. Receiving end does not exist"
*   **Symptom**: The task immediately fails on the backend with this error message.
*   **Cause**: The service worker tried to send the prompt to the ChatGPT tab before the tab's content scripts were fully injected and running. This happens when:
    *   The extension was recently reloaded/updated, but the open ChatGPT tab was not refreshed.
    *   The tab was discarded by Chrome's **Memory Saver** and was still reloading when the message was sent.
*   **How to Debug & Self-Heal**:
    1.  **Self-Healing (Automatic)**: Nancy now has an automatic, built-in self-healing reload hook! If `sendMessage` fails, it reloads the tab programmatically, pauses 3.5 seconds, and cleanly retries the dispatch.
    2.  **Manual Refresh**: If it still fails, simply go to your ChatGPT tab and press **F5 (Refresh)**. This will manually inject the latest reloaded content scripts into the page.

### Present/Potential Bug: "No active tabs found matching provider"
*   **Symptom**: Logs show `Provider adapter '<provider>' is not supported` or `Could not locate matching tab`.
*   **Cause**: No open tabs match the provider's URL patterns (e.g. `chatgpt.com` or `gemini.google.com`), or the tab URL patterns changed.
*   **How to Debug**:
    1.  Check that you actually have a tab open for the requested chatbot.
    2.  If the chatbot provider recently changed their domain structure (e.g., OpenAI moving from `chat.openai.com` to `chatgpt.com`), make sure the URL patterns are updated inside your provider's adapter class (e.g., `extension/adapters/chatgpt.js`).

---

## ─── 3. Keystroke Simulation and Submission Failures ───

### Present/Potential Bug: "Could not locate prompt input element"
*   **Symptom**: Prompt is received but typing does not begin, throwing this selector error.
*   **Cause**: Chatbot developers updated their web interface, changing the HTML ID or class names of the main prompt text editor.
*   **How to Debug & Fix**:
    1.  Go to the chatbot page, right-click the text area, and click **Inspect Element**.
    2.  Check the CSS selectors (e.g. `#prompt-textarea`, `div[contenteditable="true"]`).
    3.  Open the provider's adapter file (e.g. `extension/adapters/chatgpt.js`) and add the new selector to the top of `inputSelectors`:
        ```javascript
        get inputSelectors() {
          return [
            'new-selector-here', // Add at the top!
            '#prompt-textarea',
            ...
          ];
        }
        ```

### Present/Potential Bug: "Could not locate send button"
*   **Symptom**: The prompt types successfully but is never submitted.
*   **Cause**: The page hides or disables the send button in the DOM until input text is typed, or the selector changed.
*   **How to Debug & Fix**:
    1.  **Typing Order (Fixed)**: Nancy has been updated to query for the submit button **after** the typing simulation finishes! This guarantees that the button has been generated and enabled by the page's React/Vue state.
    2.  If the selector changed, inspect the send button in Chrome DevTools and add the new class name or attribute to the provider's `submitSelectors` list.

---

## ─── 4. Fetch Stream Interception Failures ───

### Future/Potential Bug: Interception breaks after Chatbot API changes
*   **Symptom**: Real-time fetch stream interception fails, and the task falls back to DOM MutationObserver scraping (which works, but is slightly slower and debounced).
*   **Cause**: The chatbot developers changed the internal HTTP endpoint URL path where they send conversation completions (e.g., changing `/backend-api/conversation` to a new path).
*   **How to Debug & Fix**:
    1.  Open Chrome DevTools on the chatbot page, go to the **Network** tab, type a prompt manually, and look for active event-stream connections.
    2.  Find the new endpoint path and copy it.
    3.  Open [`extension/content-scripts/main-interceptor.js`](file:///c:/Users/LOQ/nancy/extension/content-scripts/main-interceptor.js) and add the new path to `TARGET_PATTERNS`.
    4.  If the JSON structure of the SSE chunks changed, update the provider's parser function (e.g., `parseChatGPTChunk(json)`) to correctly grab the new content paths.

---

## ─── 5. How to Debug Each Layer (Step-by-Step) ───

### Step A: Inspecting the Service Worker (The Core Hub)
The Service Worker coordinates everything. To see its real-time console logs:
1.  Go to `chrome://extensions/`.
2.  Click **service worker** on the Nancy card.
3.  A dedicated DevTools window will open. Click the **Console** tab to see connection streams, task assignments, heartbeats, and tab focus activities!

### Step B: Inspecting the Chatbot Page Console
To inspect input simulations and fetch interceptions:
1.  Open your active ChatGPT tab.
2.  Press **F12** (or right-click → Inspect) and click **Console**.
3.  Filter by `[Nancy]` or check messages bridged via `postMessage`. This will show you exactly if fetch interception hijacked the SSE stream or if the DOM Observer had to fall back.

### Step C: Inspecting the FastAPI Server Logs
If hosted on Hugging Face Spaces:
1.  Go to your Hugging Face Space page.
2.  Click the **Logs** tab at the top of the page.
3.  This shows uvicorn server connections, Pydantic request validations, Redis connection status, and task assignments in real-time.
