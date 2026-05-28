# Nancy — Project Context & Resume Document (v2 Expanded)

This document serves as the absolute "Brain State / Context Resume" for Nancy. If you are continuing this development in a new chat session, feed this document to the AI assistant to resume pair programming with 100% context parity, zero friction, and minimal token usage.

---

## ─── 1. Core Mission & Constraints ───
- **System Name**: Nancy.
- **Mission**: Convert free chatbot web portals (ChatGPT, Gemini, DeepSeek, Kimi, Claude, NVIDIA NIM, z.ai) into standard, OpenAI-compatible APIs that autonomous agent swarms (like **Ultron**) can use as their high-token reasoning backbone—with **zero laptop CPU/RAM overhead**.
- **Constraint**: All processing (routing, queuing, Redis caching, Pydantic validations, API serving, multi-conversation session tracking) runs in the cloud on a Hugging Face Space (Docker, free tier: 2 vCPU, 16GB RAM). The laptop only runs lightweight, human-like DOM actions via a Chrome Extension.
- **Security**: Hardcoded credentials in repository files are strictly prohibited. All keys are managed via Hugging Face Repository Secrets and local git-ignored `.env` files.

---

## ─── 2. System Architecture (v2 Expanded) ───

```
┌────────────────────────────────────────────────────────────────────────┐
│                          ULTRON / TEST AGENT                           │
│  (LangChain Agent + Tools: nancy_chat, nancy_new_chat, nancy_switch)  │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │ OpenAI SDK (base_url = Nancy HF Space)
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│               NANCY HF SPACE v2 (FastAPI Backend)                      │
│                                                                        │
│  /v1/chat/completions    → Browser relay OR Official API bypass        │
│  /v1/sessions            → REST: Session management (list/create/kill) │
│  /admin                  → Control Center: Real-time UI Dashboard     │
└────────────┬───────────────────────────────────────────────┬──────────┘
             │ SSE Tasks                                      │ Direct API
             ▼                                                ▼
┌────────────────────────┐              ┌──────────────────────────────┐
│  CHROME EXTENSION v2   │              │  OFFICIAL API PROVIDERS      │
│                        │              │  (Mistral, NVIDIA NIM API,   │
│  + NIM Portal Adapter  │              │   DeepSeek API, Anthropic,   │
│  + z.ai Portal Adapter │              │   z.ai API)                  │
│  + Session Manager     │              └──────────────────────────────┘
│    (new chat / resume) │
│  + Multi-Tab Tracker   │
└────────────┬───────────┘
             │ DOM Interactions
             ▼
┌────────────────────────────────────────────────────────────────────────┐
│              CHATBOT PORTALS (Browser Tabs)                            │
│  ChatGPT | Gemini | DeepSeek | Kimi | Claude | NIM Portal | z.ai       │
└────────────────────────────────────────────────────────────────────────┘
```

### Layer A: The Cloud (FastAPI Backend)
*   **OpenAI compatible gateway**: Exposes `/v1/chat/completions`, `/v1/models`.
*   **Rate Limits & Circuit Breaker**: Tracks RPM rate limits, trips after 3 consecutive failures, and fails over across ChatGPT → Gemini → DeepSeek → Kimi → Claude.
*   **Session Persistence**: REST API at `/v1/sessions` backed by **Upstash Redis REST API** handles session CRUD. Allows clients to start a `new_chat`, resume conversations (`resume_chat`), or query active sessions.
*   **Server-Side Tool Overlay**: Intercepts LLM outputs to parse custom `tool_calls` JSON blocks. Exposes web search and session management tools to agents directly, returning standard OpenAI tool deltas.
*   **Glassmorphic Monitoring Dashboard**: Exposes a real-time health dashboard at `/admin` tracking queue depths, connection statuses, circuit breaker states, and active sessions.

### Layer B: The Browser Relay (Chrome Extension MV3)
*   **Service Worker (`service-worker.js`)**: Connects to the Space via persistent `fetch` stream readers. Orchestrates multi-tab mapping, parses session instructions, and triggers tab navigation (`new_chat` starts fresh URL, `resume_chat` navigates straight to saved URL).
*   **Adapters Hub**:
    *   *NIM Playground (`nim.js`)*: Intercepts the discover playground interface at `build.nvidia.com/explore/discover`.
    *   *z.ai Chat (`zai.js`)*: Selectors for elements on `chat.z.ai`.
    *   *Standard relays*: Selectors and extractors for ChatGPT, Gemini, DeepSeek, Kimi, Claude.
*   **Keystroke Simulator & Interceptor**: Mimics human typing cadence and monkey-patches `window.fetch` inside the MAIN page world to hijack SSE streams directly.

---

## ─── 3. Core Milestones Achieved ───

1.  **Phase 1 — Browser Adapters**: Created full-fledged adapters for **NVIDIA NIM Portal** (`extension/adapters/nim.js`) and **z.ai** (`extension/adapters/zai.js`). Registered URL selectors and observances.
2.  **Phase 2 — Session Manager**: Designed a Redis-backed multi-conversation session engine. The extension can dynamically spin up fresh tabs (`new_chat`), navigate directly to active urls (`resume_chat`), and feedback tab URL states for persistent URL indexing.
3.  **Phase 3 — Server-Side Tool calling**: Integrated standard OpenAI `tools` and `tool_choice` parameters. Uses a smart JSON output parser and stream buffers to intercept chatbot outputs and convert them to standard OpenAI tool execution responses seamlessly.
4.  **Phase 4 — LangChain Test Agent**: Implemented `agent/test_agent.py` covering 7 progressive test scenarios checking single-turn, memory context, fallback failovers, session toolkits, hybrid bypass, streams, and parallel swarm queueing.
5.  **Phase 5 — Control Center Dashboard**: Built a premium dark-mode dashboard at `/admin` displaying metrics, circuit breaker states, task queues, and active sessions.

---

## ─── 4. Project Directory Structure ───
```
nancy/
├── extension/                          # Chrome Extension (Manifest V3)
│   ├── manifest.json                   # Extension settings
│   ├── service-worker.js               # Background orchestrator & tab navigation
│   ├── content-scripts/
│   │   ├── isolated-observer.js        # DOM watcher delta fallback & task listener
│   │   ├── main-interceptor.js         # MAIN world fetch stream interceptor
│   │   └── input-simulator.js          # Human-like Gaussian typing simulator
│   ├── adapters/
│   │   ├── base.js                     # Base adapter interface
│   │   ├── chatgpt.js                  # ChatGPT UI selectors
│   │   ├── gemini.js                   # Google Gemini adapter
│   │   ├── deepseek.js                 # DeepSeek adapter
│   │   ├── kimi.js                     # Kimi (Moonshot) adapter
│   │   ├── claude.js                   # Claude adapter
│   │   ├── nim.js                      # NEW: NVIDIA NIM Portal adapter
│   │   └── zai.js                      # NEW: z.ai adapter
│   ├── side-panel/
│   │   ├── panel.html                  # Glassmorphic side panel HTML
│   │   └── panel.js                    # Form saving & logs JS
│   └── icons/
│
├── agent/                              # Local LangChain Test Harness
│   ├── test_agent.py                   # 7-Scenario progressive testing agent
│   ├── requirements.txt                # openai, langchain dependencies
│   └── .env.example                    # Local configuration environment example
│
└── hf-space/                           # HuggingFace Space Backend (FastAPI)
    ├── Dockerfile                      # Docker container config (port 7860)
    ├── requirements.txt                # FastAPI, sse-starlette, duckduckgo-search, jinja2
    ├── main.py                         # Startup lifespan hooks & CORS
    ├── config.py                       # Settings and API keys configuration
    ├── routers/
    │   ├── api.py                      # OpenAI completions & tool-calling
    │   ├── extension.py                # SSE task server /ext/tasks/stream
    │   ├── sessions.py                 # REST Session CRUD router
    │   ├── admin.py                    # Control center HTML endpoint
    │   └── health.py                   # Health & active session status
    └── core/
        ├── router.py                   # ProviderRouter fallback & rate limit
        ├── queue.py                    # asyncio.Queue task managers
        ├── redis_client.py             # httpx REST Upstash client
        ├── sessions.py                 # Session Records store persistence
        ├── tools.py                    # Server-side tool execution handlers
        └── auth.py                     # API key & extension auth
```

---

## ─── 5. Current Project Status ───
- **Hugging Face Space**: Deployed and fully running!
- **Redis Sessions & Multi-Tab Routing**: Fully wired up. Standard OpenAI client requests can carry `user="session:<session_id>"` to resume existing tabs or `user="new_chat"` to open a new conversation.
- **Tool calling**: Intercepts chatbot text output to trigger tool deltas gracefully.
- **Glassmorphic Monitoring Dashboard**: Registered and online at `https://<your-space-url>/admin`.

---

## ─── 6. Next Steps & Areas for Continued Development ───
1.  **Stealth Enhancements**: Introduce minor typing mistakes and backspace-corrections in `input-simulator.js` to further anonymize interactions.
2.  **Visual Captcha Triggers**: Setup standard desktop alerts or notifications in the extension side panel if a chatbot provider shows a cloudflare challenge or captcha, enabling quick human-in-the-loop solver interventions.
