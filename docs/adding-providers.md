# Adding New Chatbot Providers to Nancy

Nancy is built with a highly extensible **Adapter Pattern**. Adding support for a new chatbot web interface takes three simple steps.

---

## Step 1: Create the Adapter Module

Create a new file in `extension/adapters/<provider-key>.js` (e.g., `extension/adapters/kimi.js`). Extend the `BaseAdapter` class, define your specific UI element selectors, and register the adapter.

```javascript
import { BaseAdapter, registerAdapter } from './base.js';

class CustomAdapter extends BaseAdapter {
  /**
   * The canonical key for this provider.
   * Used for internal routing and matches the model-to-provider mappings.
   */
  get key() { return 'custom-bot'; }

  /** Friendly display name. */
  get name() { return 'Custom Bot'; }

  /**
   * Domain substrings that match this provider.
   * Used to automatically identify which tab belongs to this provider.
   */
  get urlPatterns() { return ['custom-bot.com', 'chat.custom-bot.com']; }

  /**
   * CSS selectors for the prompt entry area, in priority order.
   * Supports standard <textarea> and rich ProseMirror contenteditable containers.
   */
  get inputSelectors() {
    return [
      '#prompt-input-id',
      'div[contenteditable="true"][aria-label="Send a message"]',
      '[contenteditable="true"]',
    ];
  }

  /** CSS selectors for the send/submit button. */
  get submitSelectors() {
    return [
      'button[aria-label="Send message"]',
      'button.submit-button-class',
    ];
  }

  /**
   * CSS selector for the assistant response containers.
   * Nancy will query all nodes matching this selector and capture the *last* one.
   */
  get responseSelector() {
    return 'div[class*="assistant-message-wrapper"]';
  }

  /**
   * CSS selector that exists ONLY while the assistant is streaming text.
   * Used as a fallback check to know when generation has completed.
   */
  get streamingIndicator() {
    return '.is-generating-class, [class*="loading-indicator"]';
  }
}

// Instantiate and register
const customAdapter = new CustomAdapter();
registerAdapter(customAdapter);

export default customAdapter;
export { CustomAdapter };
```

---

## Step 2: Register in the Service Worker

To ensure your adapter registers itself when the extension service worker initializes, import your new adapter file in `extension/service-worker.js`:

```javascript
import './adapters/chatgpt.js';
import './adapters/gemini.js';
import './adapters/deepseek.js';
import './adapters/kimi.js';
import './adapters/claude.js';
import './adapters/custom-bot.js'; // <── Add your import here!
```

---

## Step 3: Register Selectors in the Content Script

Open `extension/content-scripts/isolated-observer.js` and add your provider configuration to the `PROVIDERS` dictionary. This enables DOM fallbacks and input simulation to know which selectors to use on your page:

```javascript
const PROVIDERS = {
  chatgpt: { ... },
  gemini: { ... },
  // ...
  'custom-bot': {
    name: 'Custom Bot',
    input: ['#prompt-input-id', 'div[contenteditable="true"][aria-label="Send a message"]', '[contenteditable="true"]'],
    submit: ['button[aria-label="Send message"]', 'button.submit-button-class'],
    response: 'div[class*="assistant-message-wrapper"]',
    streaming: '.is-generating-class, [class*="loading-indicator"]',
  }
};
```

---

## Optional: Intercepting API Fetch Requests

For maximum speed and bypass of DOM scraping delays, you can intercept the raw event-stream responses from the chatbot's internal API!

1. Open `extension/content-scripts/main-interceptor.js`.
2. Add your chatbot's internal message completion endpoint path to `TARGET_PATTERNS`:
   ```javascript
   const TARGET_PATTERNS = [
     '/backend-api/conversation',
     // ...
     '/api/v1/custom-bot/chat-stream', // Add here!
   ];
   ```
3. Implement a custom chunk text extractor inside `main-interceptor.js`:
   ```javascript
   function parseCustomBotChunk(json) {
     // Inspect the incoming chunk JSON structure and extract the text delta
     return json?.choices?.[0]?.delta?.content || json?.text || null;
   }
   ```
4. Map the extractor inside `extractDelta()`:
   ```javascript
    switch (provider) {
      case 'chatgpt': return parseChatGPTChunk(json);
      // ...
      case 'custom-bot': return parseCustomBotChunk(json);
      default: return null;
    }
    ```
5. Done! Your new provider will now leverage ultra-fast fetch stream interception alongside MutationObserver DOM fallbacks!

---

## ─── Step 5: Hybrid API Routing (NVIDIA NIM, Mistral, z.ai) ───

For complex, hierarchical systems (like your **Ultron** multi-agent swarm), you can combine Nancy's free browser-session workers (for massive token-consuming coding/research generation) with high-reliability **official APIs** (like NVIDIA NIM, Mistral, or z.ai) for orchestration, verification, and memory sync loops.

Here is how you can easily scale up the FastAPI backend to route to official APIs:

### 1. Add API Secrets to Hugging Face
Add your provider credentials as secure Repository Secrets in your Space settings:
- `MISTRAL_API_KEY`
- `NVIDIA_NIM_API_KEY`
- `Z_AI_API_KEY`

### 2. Register Official Models in Router
Open [`hf-space/core/router.py`](file:///c:/Users/LOQ/nancy/hf-space/core/router.py) and add your official models to the `MODEL_TO_PROVIDER` mapping. Demarcate them as official APIs rather than local extension tasks:

```python
MODEL_TO_PROVIDER: dict[str, str] = {
    # Free Browser Workers (Relayed via Extension)
    "chatgpt": "chatgpt",
    "gemini": "gemini",
    "deepseek": "deepseek",
    
    # Official API Workers (Bypasses Extension Queue)
    "mistral-large": "api-mistral",
    "nvidia-llama3": "api-nvidia-nim",
    "z-ai-instant": "api-z-ai",
}
```

### 3. Handle API Streams in the Chat completions Endpoint
Open [`hf-space/routers/api.py`](file:///c:/Users/LOQ/nancy/hf-space/routers/api.py). Inside the `chat_completions` endpoint, if the selected provider starts with `api-`, bypass the extension task queue entirely and perform a direct HTTPS stream fetch to the official endpoint:

```python
import httpx

if selected_provider.startswith("api-"):
    # Define target endpoint and headers based on provider
    if selected_provider == "api-mistral":
        api_url = "https://api.mistral.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.mistral_api_key}"}
    elif selected_provider == "api-nvidia-nim":
        api_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.nvidia_nim_api_key}"}
        
    async def official_stream_generator():
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", api_url, headers=headers, json=request.model_dump()) as resp:
                async for chunk in resp.aiter_bytes():
                    yield {"data": chunk.decode('utf-8')}
                    
    return EventSourceResponse(official_stream_generator())
```

This hybrid routing architecture provides the ultimate balance of cost-efficiency and reliable task execution, giving your multi-agent organizations a robust, industrial-grade foundation!
