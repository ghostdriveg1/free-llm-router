"""
Ultron Lite — Interactive Agent Testing Web Harness.

A beautiful, glassmorphic dark-mode web application that runs a standard ReAct 
agent loop with tool-calling capabilities. Exposes tools directly to the agent
and streams thoughts, tool executions, and responses live to a chat interface.
"""

from __future__ import annotations

import os
import json
import logging
import asyncio
import httpx
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Load configuration
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ultron.agent")

app = FastAPI(
    title="Ultron Lite",
    description="Interactive testing agent for Nancy API and Chrome extension validation",
    version="0.1.0"
)

# ─── Configuration ────────────────────────────────────────────────────────────
NANCY_BASE_URL = os.getenv("NANCY_BASE_URL", "https://ghostdrive1-nancy.hf.space/v1")
NANCY_API_KEY = os.getenv("NANCY_API_KEY", "nancy_api_key_5d2b7e19fc380e227a3c")
DEFAULT_MODEL = os.getenv("NANCY_MODEL", "chatgpt")

# ─── Server-Side Tools Implementation ─────────────────────────────────────────

async def web_search(query: str) -> str:
    """Search the web for real-time information."""
    logger.info("Executing tool web_search: '%s'", query)
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=4))
            if not results:
                return "No search results found."
            output = []
            for i, r in enumerate(results, 1):
                output.append(f"[{i}] {r.get('title')}\nURL: {r.get('href')}\nSnippet: {r.get('body')}\n")
            return "\n".join(output)
    except Exception as e:
        logger.error("Web search failed: %s", e)
        return f"Error executing web search: {str(e)}"

async def nancy_new_chat(provider: str, system_prompt: str | None = None) -> str:
    """Spawns a brand new conversation tab session."""
    logger.info("Executing tool nancy_new_chat for provider '%s'", provider)
    try:
        sess_url = f"{NANCY_BASE_URL.replace('/v1', '')}/v1/sessions"
        headers = {"Authorization": f"Bearer {NANCY_API_KEY}"}
        payload = {"provider": provider, "system_prompt": system_prompt}
        async with httpx.AsyncClient() as client:
            resp = await client.post(sess_url, headers=headers, json=payload, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return json.dumps({
                    "status": "success",
                    "session_id": data.get("session_id"),
                    "provider": data.get("provider"),
                    "message": "New session created successfully. Resume it in future messages using the session ID."
                })
            return f"Failed to create session: {resp.text}"
    except Exception as e:
        return f"Error: {str(e)}"

async def nancy_list_sessions() -> str:
    """Lists all active saved sessions in Nancy."""
    logger.info("Executing tool nancy_list_sessions")
    try:
        sess_url = f"{NANCY_BASE_URL.replace('/v1', '')}/v1/sessions"
        headers = {"Authorization": f"Bearer {NANCY_API_KEY}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(sess_url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                return json.dumps(resp.json())
            return f"Failed to list sessions: {resp.text}"
    except Exception as e:
        return f"Error: {str(e)}"

async def read_codebase() -> str:
    """Reads the entire Nancy codebase files (routers, core logic, schemas, and extension adapters) to audit or debug."""
    logger.info("Executing tool read_codebase")
    try:
        vault_path = "nancy_source_vault.txt"
        if os.path.exists(vault_path):
            with open(vault_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Return first 120,000 characters to keep it safe inside context limits
            return content[:120000]
        return "Error: Codebase vault file (nancy_source_vault.txt) not found in the container."
    except Exception as e:
        logger.error("Failed to read codebase vault: %s", e)
        return f"Error reading codebase: {str(e)}"

# Tools registry mapping
TOOLS_MAP = {
    "web_search": web_search,
    "nancy_new_chat": nancy_new_chat,
    "nancy_list_sessions": nancy_list_sessions,
    "read_codebase": read_codebase
}

TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Query the web for real-time information or lookups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "nancy_new_chat",
            "description": "Create a new conversation tab session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Chatbot model e.g. chatgpt, gemini, nim, zai"},
                    "system_prompt": {"type": "string", "description": "Optional custom system instructions"}
                },
                "required": ["provider"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "nancy_list_sessions",
            "description": "Retrieve the list of active saved conversation sessions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_codebase",
            "description": "Reads the entire Nancy codebase repository files (including content-scripts, adapters, main orchestrator, queues, sessions, and routes) to scan for bugs, analyze execution paths, or write refactoring diffs.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

# ─── Chat Request Spec ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = DEFAULT_MODEL
    session_id: str | None = None

# ─── Agent Loop SSE Engine ───────────────────────────────────────────────────

async def agent_stream_loop(query: str, model_provider: str, session_id: str | None) -> AsyncGenerator[dict, None]:
    """
    Executes a standard ReAct agent loop.
    Intercepts tool call instructions, executes them locally on this server,
    appends results to message context, and streams everything back to the web UI.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NANCY_API_KEY}"
    }
    
    # Base endpoint URL
    chat_url = f"{NANCY_BASE_URL.replace('/v1', '')}/v1/chat/completions"

    # Prepare message context
    system_prompt = (
        "You are 'Claude Mythos', a legendary software engineer and system architect with supreme "
        "comprehension of distributed systems, browser MV3 extensions, and FastAPI endpoints. "
        "You have direct access to read the complete Nancy codebase (including background workers, "
        "interceptors, and schemas) using the 'read_codebase' tool. "
        "Your task is to identify deep architectural bugs, race conditions, browser tab focus lockups, "
        "and exception handling gaps. When asked to check for bugs, audit code, or explain Nancy, you "
        "MUST first run the 'read_codebase' tool to inspect the codebase! "
        "Provide a systematic pathology report on failures and how to fix them."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]
    
    user_header = session_id if session_id else None

    # Maximum iterations to prevent infinite loop
    max_steps = 3
    step = 0
    
    async with httpx.AsyncClient() as client:
        while step < max_steps:
            step += 1
            logger.info("Agent Step %d: Submitting message context to Nancy...", step)
            
            # Send SSE stream chunk stating the agent is calling Nancy
            yield {"event": "status", "data": f"Submitting context to {model_provider} (Step {step})..."}

            payload = {
                "model": model_provider,
                "messages": messages,
                "tools": TOOLS_SCHEMAS,
                "stream": False # Non-streaming for tool-call analysis reliability
            }
            if user_header:
                payload["user"] = f"session:{user_header}"

            try:
                resp = await client.post(chat_url, headers=headers, json=payload, timeout=90.0)
                if resp.status_code != 200:
                    yield {"event": "error", "data": f"Nancy Error: {resp.status_code} - {resp.text}"}
                    return
                
                resp_json = resp.json()
                choice = resp_json["choices"][0]
                msg = choice["message"]
                
                # Check for tool call
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # Capture tool instructions
                    messages.append(msg)
                    for tc in tool_calls:
                        call_id = tc.get("id")
                        func = tc["function"]
                        name = func["name"]
                        args_str = func["arguments"]
                        
                        try:
                            args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        except:
                            args = {"query": str(args_str)}

                        yield {"event": "tool_call", "data": json.dumps({"name": name, "arguments": args})}
                        
                        # Execute Tool
                        handler = TOOLS_MAP.get(name)
                        if handler:
                            yield {"event": "status", "data": f"Running tool '{name}' server-side..."}
                            # Unpack arguments appropriately
                            if name == "web_search":
                                result = await handler(args.get("query", ""))
                            elif name == "nancy_new_chat":
                                result = await handler(args.get("provider", ""), args.get("system_prompt"))
                            else:
                                result = await handler()
                        else:
                            result = f"Error: Tool '{name}' is not registered."

                        yield {"event": "tool_result", "data": json.dumps({"name": name, "result": result[:800] + '...' if len(result) > 850 else result})}
                        
                        # Append tool output to context
                        messages.append({
                            "role": "tool",
                            "name": name,
                            "tool_call_id": call_id,
                            "content": result
                        })
                else:
                    # Final text response obtained
                    content = msg.get("content", "")
                    yield {"event": "final_result", "data": content}
                    return

            except Exception as e:
                logger.error("Exception in Agent ReAct loop: %s", e)
                yield {"event": "error", "data": f"Agent loop failed: {str(e)}"}
                return

        # If we exceed max steps
        yield {"event": "final_result", "data": "Error: Maximum agent iterations reached without final resolution."}

class SessionRequest(BaseModel):
    provider: str

@app.post("/new_session")
async def new_session_proxy(req: SessionRequest):
    """Proxy endpoint to create a new session on Nancy."""
    try:
        sess_url = f"{NANCY_BASE_URL.replace('/v1', '')}/v1/sessions"
        headers = {"Authorization": f"Bearer {NANCY_API_KEY}"}
        payload = {"provider": req.provider}
        async with httpx.AsyncClient() as client:
            resp = await client.post(sess_url, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "message": f"Nancy HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Event source stream for agent actions."""
    async def sse_wrapper():
        async for chunk in agent_stream_loop(req.message, req.model, req.session_id):
            yield chunk
            
    return EventSourceResponse(sse_wrapper())

# ─── Glassmorphic Web UI HTML ────────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ultron Lite — Agent Testing Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #07080d;
            --panel-bg: rgba(13, 16, 28, 0.7);
            --border-glow: rgba(139, 92, 246, 0.25);
            --primary: #8b5cf6;
            --primary-glow: rgba(139, 92, 246, 0.4);
            --accent: #06b6d4;
            --accent-glow: rgba(6, 182, 212, 0.3);
            --success: #10b981;
            --warning: #f59e0b;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 10%, rgba(139, 92, 246, 0.12) 0%, transparent 40%),
                radial-gradient(circle at 90% 90%, rgba(6, 182, 212, 0.08) 0%, transparent 40%);
            background-attachment: fixed;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 1.5rem;
            display: grid;
            grid-template-rows: auto 1fr;
            height: 100vh;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 1rem;
            margin-bottom: 1rem;
        }

        .logo-section h1 {
            font-size: 1.6rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a78bfa 0%, #22d3ee 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .logo-section h1::before {
            content: '';
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #a78bfa;
            border-radius: 3px;
            box-shadow: 0 0 10px #a78bfa;
        }

        .logo-section p {
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        /* Layout Grid */
        .workspace {
            display: grid;
            grid-template-columns: 280px 1fr;
            gap: 1.5rem;
            height: 82vh;
            overflow: hidden;
        }

        @media (max-width: 900px) {
            .workspace {
                grid-template-columns: 1fr;
            }
            .sidebar {
                display: none;
            }
        }

        /* Sidebar Glass panel */
        .sidebar {
            background: var(--panel-bg);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
            backdrop-filter: blur(10px);
        }

        .input-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        label {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
        }

        select, input[type="text"] {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 0.6rem 0.8rem;
            color: var(--text-main);
            font-family: inherit;
            font-size: 0.85rem;
            outline: none;
            transition: all 0.2s ease;
        }

        select:focus, input[type="text"]:focus {
            border-color: var(--primary);
            box-shadow: 0 0 10px rgba(139, 92, 246, 0.2);
        }

        .badge {
            background: rgba(255, 255, 255, 0.05);
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            font-size: 0.7rem;
            align-self: flex-start;
        }

        /* Chat Panel Glass panel */
        .chat-panel {
            background: var(--panel-bg);
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
            backdrop-filter: blur(10px);
        }

        .chat-feed {
            flex: 1;
            padding: 1.5rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        /* Message Bubbles */
        .msg {
            max-width: 85%;
            padding: 1rem 1.2rem;
            border-radius: 16px;
            font-size: 0.92rem;
            line-height: 1.5;
            position: relative;
        }

        .msg-user {
            background: linear-gradient(135deg, rgba(139, 92, 246, 0.15), rgba(139, 92, 246, 0.05));
            border: 1px solid rgba(139, 92, 246, 0.2);
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }

        .msg-thought {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            color: var(--text-muted);
            border-left: 3px solid var(--accent);
            font-style: italic;
            font-size: 0.85rem;
        }

        .msg-tool {
            background: rgba(245, 158, 11, 0.03);
            border: 1px solid rgba(245, 158, 11, 0.15);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            color: var(--warning);
            font-family: monospace;
            font-size: 0.8rem;
        }

        .msg-agent {
            background: linear-gradient(135deg, rgba(6, 182, 212, 0.15), rgba(6, 182, 212, 0.05));
            border: 1px solid rgba(6, 182, 212, 0.2);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            box-shadow: 0 4px 15px rgba(6, 182, 212, 0.05);
        }

        .bubble-label {
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.4rem;
            display: block;
        }

        /* Message input area */
        .chat-input-area {
            padding: 1.2rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            background: rgba(0, 0, 0, 0.2);
            display: flex;
            gap: 0.8rem;
        }

        .chat-input {
            flex: 1;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 0.8rem 1rem;
            color: var(--text-main);
            font-family: inherit;
            outline: none;
            font-size: 0.95rem;
            transition: all 0.2s ease;
        }

        .chat-input:focus {
            border-color: var(--primary);
            background: rgba(255, 255, 255, 0.04);
        }

        .send-btn {
            background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%);
            border: none;
            color: white;
            padding: 0 1.5rem;
            border-radius: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s ease;
        }

        .send-btn:hover {
            opacity: 0.9;
        }

        .sys-state {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 1rem;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-section">
                <h1>ULTRON LITE</h1>
                <p>Interactive Agent Testing Harness for Nancy v2</p>
            </div>
            <span class="badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success);">AGENT ONLINE</span>
        </header>

        <div class="workspace">
            <!-- Sidebar configs -->
            <div class="sidebar">
                <div class="input-group">
                    <label>Nancy Target Model</label>
                    <select id="model-select">
                        <option value="chatgpt">ChatGPT (Browser)</option>
                        <option value="gemini">Gemini (Browser)</option>
                        <option value="nim">NVIDIA NIM Portal (Browser)</option>
                        <option value="zai">z.ai Portal (Browser)</option>
                        <option value="mistral-large">Mistral API (Bypass)</option>
                        <option value="z-ai-api">z.ai API (Bypass)</option>
                    </select>
                </div>

                <div class="input-group">
                    <label>Active Session ID</label>
                    <input type="text" id="session-input" placeholder="e.g. uuid-key (Optional)">
                    <p style="font-size: 0.7rem; color: var(--text-muted); margin-top:0.2rem;">Resumes or links tab sessions dynamically</p>
                </div>

                <div class="input-group" style="margin-top: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem;">
                    <button class="send-btn" id="new-session-btn" style="padding: 0.6rem; font-size: 0.8rem; height: auto; border-radius: 8px;">Start New Chat Session</button>
                    <span id="session-status" style="font-size: 0.72rem; color: var(--success); text-align: center; display: none; font-weight: 500;"></span>
                </div>

                <div style="margin-top: auto; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 1rem;">
                    <label>Available Agent Tools</label>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem;">
                        <span class="badge" style="color: var(--accent);">web_search</span>
                        <span class="badge" style="color: var(--accent);">nancy_new_chat</span>
                        <span class="badge" style="color: var(--accent);">nancy_list_sessions</span>
                        <span class="badge" style="color: var(--accent);">read_codebase</span>
                    </div>
                </div>
            </div>

            <!-- Chat screen -->
            <div class="chat-panel">
                <div class="chat-feed" id="chat-feed">
                    <!-- Default greeting -->
                    <div class="msg msg-agent">
                        <span class="bubble-label" style="color: var(--accent);">ULTRON AGENT</span>
                        Hello! I am Ultron Lite, a fully-featured ReAct test agent. I communicate directly with your Nancy space and have native access to server-side tools like web search and multi-tab session switching. Ask me a complex question requiring search or session control to watch me work!
                    </div>
                </div>

                <!-- Input area -->
                <div class="chat-input-area">
                    <input type="text" class="chat-input" id="chat-input" placeholder="Ask Ultron something (e.g. 'search the web for weather in Tokyo')...">
                    <button class="send-btn" id="send-btn">ENGAGE</button>
                </div>
            </div>
        </div>
        <div class="sys-state">
            Connected Endpoint: <span style="color: var(--primary); font-family: monospace;">{nancy_url}</span>
        </div>
    </div>

    <script>
        const chatFeed = document.getElementById("chat-feed");
        const chatInput = document.getElementById("chat-input");
        const sendBtn = document.getElementById("send-btn");
        const modelSelect = document.getElementById("model-select");
        const sessionInput = document.getElementById("session-input");
        const newSessionBtn = document.getElementById("new-session-btn");
        const sessionStatus = document.getElementById("session-status");

        newSessionBtn.addEventListener("click", async () => {
            const provider = modelSelect.value;
            newSessionBtn.disabled = true;
            newSessionBtn.innerText = "Creating...";
            sessionStatus.style.display = "none";
            
            try {
                const resp = await fetch("/new_session", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ provider: provider })
                });
                
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.session_id) {
                        sessionInput.value = data.session_id;
                        sessionStatus.innerText = "Created New Session: " + data.session_id.substr(0, 8) + "...";
                        sessionStatus.style.display = "inline";
                    } else {
                        alert("Error creating session: " + JSON.stringify(data));
                    }
                } else {
                    alert("Error: " + resp.statusText);
                }
            } catch (err) {
                alert("Exception: " + err.message);
            } finally {
                newSessionBtn.disabled = false;
                newSessionBtn.innerText = "Start New Chat Session";
            }
        });

        function appendMessage(role, label, text, color) {
            const msgDiv = document.createElement("div");
            msgDiv.className = `msg msg-${role}`;
            
            const labelSpan = document.createElement("span");
            labelSpan.className = "bubble-label";
            labelSpan.style.color = color;
            labelSpan.innerText = label;
            
            const textDiv = document.createElement("div");
            textDiv.innerText = text;
            
            msgDiv.appendChild(labelSpan);
            msgDiv.appendChild(textDiv);
            chatFeed.appendChild(msgDiv);
            chatFeed.scrollTop = chatFeed.scrollHeight;
        }

        async function sendMessage() {
            const text = chatInput.value.trim();
            if (!text) return;

            chatInput.value = "";
            appendMessage("user", "USER QUERY", text, "#a78bfa");

            // Prepare payload
            const payload = {
                message: text,
                model: modelSelect.value,
                session_id: sessionInput.value.trim() || null
            };

            // Call /chat SSE streaming endpoint
            try {
                const response = await fetch("/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    appendMessage("thought", "SYSTEM ERROR", "Connection failure: " + response.statusText, "var(--danger)");
                    return;
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    buffer += decoder.decode(value);
                    const lines = buffer.split("\\n");
                    buffer = lines.pop(); // Keep residue

                    for (const line of lines) {
                        if (!line.startsWith("event: ")) continue;
                        
                        // Parse event structure
                        const eventMatch = line.match(/^event: (\\w+)/);
                        if (!eventMatch) continue;
                        const event = eventMatch[1];
                        
                        // Next line holds details
                        const dataIndex = buffer.indexOf("data: ");
                        const nextLine = lines[lines.indexOf(line) + 1];
                        if (!nextLine || !nextLine.startsWith("data: ")) continue;
                        const data = nextLine.replace("data: ", "");

                        if (event === "status") {
                            appendMessage("thought", "AGENT STATUS", data, "var(--text-muted)");
                        } else if (event === "tool_call") {
                            const tc = JSON.parse(data);
                            appendMessage("tool", "TOOL CALL INSTRUCTION", `Invoking [${tc.name}] with args: ${JSON.stringify(tc.arguments)}`, "var(--warning)");
                        } else if (event === "tool_result") {
                            const tc = JSON.parse(data);
                            appendMessage("tool", "TOOL RESPONSE", `Result from [${tc.name}]:\\n${tc.result}`, "var(--success)");
                        } else if (event === "final_result") {
                            appendMessage("agent", "ULTRON FINAL RESOLUTION", data, "var(--accent)");
                        } else if (event === "error") {
                            appendMessage("thought", "AGENT ERROR", data, "var(--danger)");
                        }
                    }
                }
            } catch (err) {
                appendMessage("thought", "NETWORK EXCEPTION", err.message, "var(--danger)");
            }
        }

        sendBtn.addEventListener("click", sendMessage);
        chatInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") sendMessage();
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    """Renders the main glassmorphic chat page."""
    rendered = DASHBOARD_HTML.replace("{nancy_url}", NANCY_BASE_URL)
    return HTMLResponse(content=rendered)
