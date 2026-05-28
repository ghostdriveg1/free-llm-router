# Nancy System Architecture

Nancy is a distributed relay orchestrator designed to bridge AI Agents with free, authenticated chatbot web interfaces. The core design principle is **extreme visual efficiency with zero local CPU/RAM overhead** on your main machine.

---

## High-Level Topology

```
┌─────────────────┐              ┌──────────────────────┐              ┌─────────────────────────┐
│                 │              │                      │              │                         │
│    AI AGENT     │  OpenAI API  │    NANCY HF SPACE    │  SSE Stream  │     CHROME EXTENSION    │
│  (langchain,    ├─────────────►│ (FastAPI, Orchestrator)│◄─────────────┤  (Browser, MV3 Relay)   │
│   crewai, etc.) │              │                      │              │                         │
└─────────────────┘              └──────────────────────┘              └────────────┬────────────┘
                                                                                    │ Keystrokes
                                                                                    ▼
                                                                       ┌─────────────────────────┐
                                                                       │    CHATBOT INTERFACES   │
                                                                       │ (ChatGPT, Gemini, etc.) │
                                                                       └─────────────────────────┘
```

---

## 1. Cloud Layer (Hugging Face Space Backend)

The Cloud Layer runs as a containerized FastAPI application on Hugging Face Spaces (free tier: 2 vCPUs, 16GB RAM). It acts as the central middleware, exposing standard OpenAI-compatible endpoints while routing requests as asynchronous tasks.

### Task Queue & Handle Registry (`core/queue.py`)
- Each incoming `/v1/chat/completions` request generates a unique `Task` payload containing the messages and target model, and a standard OpenAI response ID (`chatcmpl-*`).
- The task is placed in an in-memory `asyncio.Queue` (with an optional backing Upstash Redis layer for persistence across container restarts).
- A `TaskHandle` is registered containing:
  - An `asyncio.Event` (`done_event`) to block non-streaming requests.
  - An `asyncio.Queue[str | None]` (`chunk_queue`) where streaming chunks are buffered as they arrive.
- The FastAPI chat handler runs an async iterator over the `chunk_queue`, yielding chunks to the client immediately using Server-Sent Events (SSE).

### Router & Failover Registry (`core/router.py`)
- Maps incoming model names (e.g. `gpt-4o`, `gemini-pro`) to their canonical provider key (`chatgpt`, `gemini`).
- Selects the target provider checking a sliding-window **RPM Rate Limiter** and a **Circuit Breaker** (consecutive failures trip the circuit to avoid blackholing requests).
- Walks a configured fallback chain if a provider is offline (e.g., trying `chatgpt` → `gemini` → `deepseek`).

---

## 2. Browser Layer (Chrome Extension)

The Browser Layer is a Manifest V3 Chrome Extension. It leverages the user's active, pre-authenticated sessions in standard Chrome browser tabs to interact with chatbot web portals.

### Service Worker (`service-worker.js`)
- Runs a persistent, streaming `fetch` connection reading from the Nancy Server task stream.
- Maintains a heartbeat POST loop (every 24 seconds) to prevent service worker suspension and report active tasks.
- Manages browser tab lifecycles: queries matching tabs, opens them automatically if missing, injects content scripts, and ensures the target tab is focused during interactions.

### Input Simulator (`content-scripts/input-simulator.js`)
- Types prompts into textareas and ProseMirror rich text editors character-by-character.
- Uses **Gaussian-distributed typing delays** calculated using the Box-Muller transform:
  - Base typing cadence of 80–120ms.
  - Muscle-memory speeds for spaces (faster) and punctuation (longer thinking pauses).
  - Simulates natural "human thinking intervals" (8% chance of pauses between 250ms and 750ms).
- Dispatches keydown, keypress, insertText, input, change, and keyup event chains to bypass simple automation detection checks.

### Hybrid Response Extraction
To maximize response capture speeds while maintaining absolute resiliency, Nancy implements a dual response extraction framework:

#### Primary: API stream interception (`content-scripts/main-interceptor.js`)
- Monkey-patches the page's standard `window.fetch` inside the **MAIN** javascript execution world.
- Intercepts requests matching known chatbot API patterns (e.g., `/backend-api/conversation` for ChatGPT).
- Hijacks the response `ReadableStream`, duplicate-pipes the events to a custom decoder, parses the raw Server-Sent Event (SSE) JSON chunks in real-time, and bridges them to the Isolated content script world using `window.postMessage`.
- Bypasses all DOM parsing delays, providing instant text streaming.

#### Fallback: DOM MutationObserver delta scraping (`content-scripts/isolated-observer.js`)
- Runs in the isolated extension world, watching the DOM subtree for mutations.
- Whenever changes are noticed, it captures the inner text of the latest assistant response container.
- Calculates the string difference (delta) against the last captured text, pushing the differences to the service worker immediately.
- Includes a 20-second inactivity timeout and settles generation after the assistant's streaming indicator vanishes.
