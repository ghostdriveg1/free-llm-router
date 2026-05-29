"""
Nancy HF Space — Admin Dashboard.

Exposes a beautiful, premium dark-mode, glassmorphic monitoring dashboard at /admin
for visualizing system health, queues, circuit breakers, and active sessions.
"""

from __future__ import annotations

import time
import uuid
import hashlib
from fastapi import APIRouter, Request, Body
from fastapi.responses import HTMLResponse


from core.queue import task_queue
from core.router import provider_router
from core.sessions import session_store
from core.redis_client import redis_client

router = APIRouter(prefix="/admin", tags=["Nancy Administration"])

# HTML template string containing premium CSS styled with glassmorphic cards and gradients
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nancy v2 — Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #090a0f;
            --panel-bg: rgba(17, 19, 31, 0.7);
            --border-glow: rgba(124, 58, 237, 0.25);
            --primary: #8b5cf6;
            --primary-glow: rgba(139, 92, 246, 0.4);
            --accent: #06b6d4;
            --accent-glow: rgba(6, 182, 212, 0.4);
            --success: #10b981;
            --danger: #ef4444;
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
                radial-gradient(circle at 10% 20%, rgba(139, 92, 246, 0.1) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.08) 0%, transparent 40%);
            background-attachment: fixed;
        }

        /* Container & Navigation */
        .container {
            max-width: 1300px;
            margin: 0 auto;
            padding: 2rem;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2.5rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 1.5rem;
        }

        .logo-section h1 {
            font-size: 1.8rem;
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
            width: 12px;
            height: 12px;
            background: #a78bfa;
            border-radius: 3px;
            box-shadow: 0 0 10px #a78bfa;
            animation: pulse-glow 2s infinite;
        }

        .logo-section p {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-top: 0.2rem;
        }

        .sys-time {
            font-size: 0.9rem;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.03);
            padding: 0.5rem 1rem;
            border-radius: 99px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--panel-bg);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            backdrop-filter: blur(10px);
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--primary-glow), transparent);
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .stat-card:hover {
            transform: translateY(-4px);
            border-color: var(--border-glow);
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
        }

        .stat-card:hover::before {
            opacity: 1;
        }

        .stat-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: var(--text-muted);
            font-size: 0.85rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 1rem;
        }

        .stat-val {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--text-main);
            letter-spacing: -1px;
            line-height: 1;
        }

        .stat-sub {
            font-size: 0.8rem;
            margin-top: 0.6rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        /* Circuit Breakers & Health Panel */
        .main-layout {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }

        @media (max-width: 968px) {
            .main-layout {
                grid-template-columns: 1fr;
            }
        }

        .panel {
            background: var(--panel-bg);
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            padding: 1.8rem;
            backdrop-filter: blur(10px);
        }

        .panel-title {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 0.8rem;
        }

        /* Provider Tables & Lists */
        .provider-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .provider-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 1.2rem;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            transition: background 0.2s ease;
        }

        .provider-row:hover {
            background: rgba(255, 255, 255, 0.04);
        }

        .provider-info {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .provider-avatar {
            width: 36px;
            height: 36px;
            border-radius: 8px;
            background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(6, 182, 212, 0.2));
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: var(--primary);
            font-size: 0.9rem;
            text-transform: uppercase;
        }

        .provider-details h3 {
            font-size: 0.95rem;
            font-weight: 600;
            margin-bottom: 0.15rem;
            text-transform: capitalize;
        }

        .provider-details span {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .status-badge {
            padding: 0.35rem 0.75rem;
            border-radius: 99px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }

        .status-healthy {
            background: rgba(16, 185, 129, 0.1);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.2);
        }

        .status-degraded {
            background: rgba(245, 158, 11, 0.1);
            color: var(--warning);
            border: 1px solid rgba(245, 158, 11, 0.2);
        }

        .status-broken {
            background: rgba(239, 68, 68, 0.1);
            color: var(--danger);
            border: 1px solid rgba(239, 68, 68, 0.2);
        }

        /* Sessions list */
        .session-item {
            padding: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .session-item:last-child {
            border-bottom: none;
        }

        .session-meta h4 {
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 0.2rem;
            color: var(--text-main);
        }

        .session-meta p {
            font-size: 0.75rem;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 250px;
        }

        .badge {
            background: rgba(255, 255, 255, 0.05);
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
            font-size: 0.7rem;
            color: var(--text-muted);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* Animations */
        @keyframes pulse-glow {
            0%, 100% {
                transform: scale(1);
                box-shadow: 0 0 10px #a78bfa;
            }
            50% {
                transform: scale(1.15);
                box-shadow: 0 0 18px #a78bfa, 0 0 5px #22d3ee;
            }
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }
        .pulse-dot.active {
            background-color: var(--success);
            box-shadow: 0 0 8px var(--success);
            animation: pulse-active 1.5s infinite;
        }
        @keyframes pulse-active {
            0% { transform: scale(0.9); opacity: 1; }
            50% { transform: scale(1.2); opacity: 0.7; }
            100% { transform: scale(0.9); opacity: 1; }
        }

        .refresh-btn {
            background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%);
            border: none;
            color: white;
            padding: 0.5rem 1.2rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s ease;
        }

        .refresh-btn:hover {
            opacity: 0.9;
        }

        /* Dynamic API Key Vault UI Styles */
        .revoke-btn {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: var(--danger);
            padding: 0.35rem 0.8rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .revoke-btn:hover {
            background: var(--danger);
            color: white;
            box-shadow: 0 0 10px rgba(239, 68, 68, 0.4);
        }
        .generate-panel {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
            align-items: center;
        }
        .api-input {
            flex: 1;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 0.6rem 1rem;
            color: white;
            font-family: inherit;
            font-size: 0.9rem;
            outline: none;
            transition: border-color 0.2s;
        }
        .api-input:focus {
            border-color: var(--primary);
        }
        .api-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        .api-table th {
            text-align: left;
            padding: 0.8rem 1rem;
            color: var(--text-muted);
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .copy-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: white;
            padding: 0.6rem 1.2rem;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .copy-btn:hover {
            background: rgba(255, 255, 255, 0.15);
        }

    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-section">
                <h1>NANCY CONTROL</h1>
                <p>Advanced Free Chatbot Orchestrator & API Router</p>
            </div>
            <div class="sys-time">
                SYS STATE: <span style="color: var(--success); font-weight:600;">OPERATIONAL</span>
            </div>
        </header>

        <!-- Stats row -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-header">
                    <span>Task Queue Depth</span>
                    <span class="badge">SSE Queue</span>
                </div>
                <div class="stat-val">{queue_depth}</div>
                <div class="stat-sub" style="color: var(--text-muted);">
                    <span class="pulse-dot active"></span> Active tasks waiting for pickup
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-header">
                    <span>Active Sessions</span>
                    <span class="badge">Redis</span>
                </div>
                <div class="stat-val">{session_count}</div>
                <div class="stat-sub" style="color: var(--text-muted);">
                    Tracked multi-conversation sessions
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-header">
                    <span>Extension Hub</span>
                    <span class="badge">Relay Status</span>
                </div>
                <div class="stat-val" style="color: var(--success);">{ext_status}</div>
                <div class="stat-sub" style="color: var(--text-muted);">
                    Clients connected in real-time
                </div>
            </div>

            <div class="stat-card">
                <div class="stat-header">
                    <span>Upstash Persistence</span>
                    <span class="badge">Cache</span>
                </div>
                <div class="stat-val" style="color: {redis_color}; font-size: 1.8rem; margin-top: 0.3rem;">{redis_status}</div>
                <div class="stat-sub" style="color: var(--text-muted);">
                    State persistence engine status
                </div>
            </div>
        </div>

        <div class="main-layout">
            <!-- Left panel: Health & Providers -->
            <div class="panel">
                <div class="panel-title">
                    <span>Provider Status & Failover Configuration</span>
                    <button class="refresh-btn" onclick="location.reload()">REFRESH STATE</button>
                </div>
                <div class="provider-list">
                    {provider_rows}
                </div>
            </div>

            <!-- Right panel: Active sessions list -->
            <div class="panel">
                <div class="panel-title">
                    <span>Active Sessions</span>
                    <span class="badge">{session_count} Total</span>
                </div>
                <div style="max-height: 400px; overflow-y: auto;">
                    {session_rows}
                </div>
            </div>
        </div>

        <!-- 🔑 Dynamic API Key Vault Panel -->
        <div class="panel" style="margin-top: 1.5rem;">
            <div class="panel-title">
                <span>🔑 Dynamic API Key Handoff Vault</span>
                <span class="badge">Redis Hashed Credentials</span>
            </div>
            
            <div style="margin-bottom: 1.5rem; background: rgba(139, 92, 246, 0.05); border: 1px solid rgba(139, 92, 246, 0.1); border-radius: 12px; padding: 1.2rem; display: flex; flex-direction: column; gap: 0.5rem;">
                <h4 style="color: #a78bfa; font-size: 0.95rem; font-weight: 600;">How to connect Ultron Swarm (or external agents)</h4>
                <p style="color: var(--text-muted); font-size: 0.85rem; line-height: 1.4;">
                    Generate a secure API key below. Paste it along with your Nancy server URL (e.g. <code>https://ghostdriveg1-free-llm-router.hf.space</code>) into the Ultron Swarm Control Dashboard. Nancy hashes and saves all keys securely using SHA-256 in Upstash Redis.
                </p>
            </div>

            <!-- New Key Generator -->
            <div class="generate-panel">
                <input type="text" id="key-desc" class="api-input" placeholder="e.g. Ultron Swarm Production Client" />
                <button class="refresh-btn" onclick="generateKey()">GENERATE ACCESS KEY</button>
            </div>

            <!-- Plaintext Key Display (Shown once on generation) -->
            <div id="key-result-container" style="display: none; margin-top: 1.2rem; padding: 1.2rem; background: rgba(16, 185, 129, 0.06); border: 1px solid rgba(16, 185, 129, 0.15); border-radius: 12px;">
                <h4 style="color: var(--success); font-size: 0.9rem; font-weight: 600; margin-bottom: 0.5rem;">Access Key Generated Successfully!</h4>
                <p style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 0.8rem;">
                    ⚠️ Copy this key now! For security reasons, you will <strong>NOT</strong> be able to view this plaintext key again.
                </p>
                <div style="display: flex; gap: 0.8rem; align-items: center;">
                    <input type="text" id="generated-key-display" class="api-input" readonly style="font-family: monospace; font-size: 0.95rem; color: var(--success); border-color: rgba(16, 185, 129, 0.25);" />
                    <button id="copy-btn" class="copy-btn" onclick="copyToClipboard()">COPY KEY</button>
                </div>
            </div>

            <!-- API Keys List Table -->
            <div style="overflow-x: auto; margin-top: 1.5rem;">
                <table class="api-table">
                    <thead>
                        <tr>
                            <th>Client Description</th>
                            <th>Key Hash (SHA-256)</th>
                            <th>Created At</th>
                            <th>Last Active</th>
                            <th style="text-align: right;">Action</th>
                        </tr>
                    </thead>
                    <tbody id="keys-tbody">
                        <tr>
                            <td colspan="5" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">
                                Loading API keys vault...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Frontend AJAX Scripting -->
    <script>
        async function loadKeys() {
            try {
                const resp = await fetch("/admin/keys/list");
                const keys = await resp.json();
                const tbody = document.getElementById("keys-tbody");
                if (!keys || keys.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">No dynamic API keys found. Generate one above!</td></tr>';
                    return;
                }
                tbody.innerHTML = keys.map(k => {
                    const date = new Date(k.created_at * 1000).toLocaleString();
                    const lastUsed = k.last_used ? new Date(k.last_used * 1000).toLocaleString() : "Never";
                    return `
                        <tr>
                            <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); font-weight: 500;">${escapeHtml(k.description)}</td>
                            <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); font-family: monospace; color: var(--accent);">${k.hash.substring(0, 12)}...</td>
                            <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text-muted); font-size: 0.85rem;">${date}</td>
                            <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text-muted); font-size: 0.85rem;">${lastUsed}</td>
                            <td style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.04); text-align: right;">
                                <button class="revoke-btn" onclick="revokeKey('${k.hash}')">REVOKE</button>
                            </td>
                        </tr>
                    `;
                }).join('');
            } catch (e) {
                console.error("Error loading keys:", e);
            }
        }

        function escapeHtml(str) {
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        async function generateKey() {
            const desc = document.getElementById("key-desc").value.trim() || "Swarm Client";
            try {
                const resp = await fetch("/admin/keys/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ description: desc })
                });
                const data = await resp.json();
                
                // Show generated key container
                const resultDiv = document.getElementById("key-result-container");
                resultDiv.style.display = "block";
                document.getElementById("generated-key-display").value = data.plaintext_key;
                
                document.getElementById("key-desc").value = "";
                await loadKeys();
            } catch (e) {
                alert("Error generating key: " + e);
            }
        }

        async function revokeKey(hash) {
            if (!confirm("Are you sure you want to revoke this API key? Connected systems using this key will immediately lose access!")) return;
            try {
                await fetch(`/admin/keys/revoke/${hash}`, { method: "DELETE" });
                await loadKeys();
            } catch (e) {
                alert("Error revoking key: " + e);
            }
        }

        function copyToClipboard() {
            const copyText = document.getElementById("generated-key-display");
            copyText.select();
            copyText.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(copyText.value);
            
            const copyBtn = document.getElementById("copy-btn");
            copyBtn.innerText = "COPIED!";
            copyBtn.style.background = "var(--success)";
            setTimeout(() => {
                copyBtn.innerText = "COPY KEY";
                copyBtn.style.background = "rgba(255,255,255,0.08)";
            }, 2000);
        }

        // Auto-run on startup
        document.addEventListener("DOMContentLoaded", loadKeys);
    </script>
</body>
</html>

"""

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Renders the control center admin status page."""
    
    # 1. Fetch current queue size
    try:
        queue_depth = task_queue.pending_count
    except Exception:
        queue_depth = 0

    # 2. Check Extension SSE connections status
    ext_connected = task_queue.is_extension_active()
    ext_status = "Connected" if ext_connected else "Offline"

    # 3. Check Redis Connection Status
    redis_active = redis_client.is_enabled
    redis_status = "ONLINE" if redis_active else "FALLBACK (IN-MEMORY)"
    redis_color = "var(--success)" if redis_active else "var(--warning)"

    # 4. Fetch Sessions list
    try:
        sessions = await session_store.list_sessions()
        session_count = len(sessions)
    except Exception:
        sessions = []
        session_count = 0

    # 5. Build dynamic session items
    session_rows = ""
    if not sessions:
        session_rows = '<div style="padding: 1.5rem; text-align: center; color: var(--text-muted); font-size: 0.85rem;">No active tracked sessions found.</div>'
    else:
        for sess in sessions[:8]: # Show top 8 active
            session_rows += f"""
            <div class="session-item">
                <div class="session-meta">
                    <h4>{sess.title}</h4>
                    <p>{sess.conversation_url or 'Fresh Chat (No URL yet)'}</p>
                </div>
                <span class="badge" style="text-transform: capitalize;">{sess.provider}</span>
            </div>
            """

    # 6. Fetch Providers circuit breaker states
    # Default list of providers
    all_providers = ["chatgpt", "gemini", "deepseek", "kimi", "claude", "nim", "zai"]
    provider_rows = ""

    for provider in all_providers:
        # Determine status
        is_healthy = provider_router.is_provider_healthy(provider)
        
        badge_class = "status-healthy" if is_healthy else "status-broken"
        status_text = "HEALTHY" if is_healthy else "DEGRADED / DRAINED"
        
        # Determine adapter fallback priority indicator
        fallback_pos = "Primary" if provider in provider_router.fallback_chain else "Bypass / API"
        if provider in provider_router.fallback_chain:
            idx = provider_router.fallback_chain.index(provider) + 1
            fallback_pos = f"Fallback Chain #{idx}"

        provider_rows += f"""
        <div class="provider-row">
            <div class="provider-info">
                <div class="provider-avatar">{provider[:2]}</div>
                <div class="provider-details">
                    <h3>{provider}</h3>
                    <span>Priority: {fallback_pos}</span>
                </div>
            </div>
            <div class="status-badge {badge_class}">
                <span class="pulse-dot active" style="background-color: currentColor;"></span>
                {status_text}
            </div>
        </div>
        """

    # Render dashboard safely using simple replacement to avoid CSS/JS brace clashes
    rendered = (
        DASHBOARD_HTML
        .replace("{queue_depth}", str(queue_depth))
        .replace("{session_count}", str(session_count))
        .replace("{ext_status}", str(ext_status))
        .replace("{redis_status}", str(redis_status))
        .replace("{redis_color}", str(redis_color))
        .replace("{session_rows}", str(session_rows))
        .replace("{provider_rows}", str(provider_rows))
    )
    
    return HTMLResponse(content=rendered)


# ── Dynamic API Key AJAX Endpoints ───────────────────────────────────────────

@router.post("/keys/create")
async def create_api_key(payload: dict = Body(default={})):
    """Generates a secure UUID API key prefixed with ny_, hashes it, and caches in Redis."""
    description = payload.get("description", "Swarm Integration Client")
    plaintext_uuid = uuid.uuid4().hex
    plaintext_key = f"ny_{plaintext_uuid}"
    hashed = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
    
    key_id = str(uuid.uuid4())
    metadata = {
        "id": key_id,
        "description": description,
        "hash": hashed,
        "created_at": int(time.time()),
        "last_used": None,
        "request_count": 0
    }
    
    # Save key metadata and register in active hashes set
    await redis_client.set_json(f"nancy:api_keys:{hashed}", metadata)
    await redis_client._execute("SADD", "nancy:active_key_hashes", hashed)
    
    return {
        "key_id": key_id,
        "plaintext_key": plaintext_key,
        "description": description,
        "created_at": metadata["created_at"]
    }


@router.get("/keys/list")
async def list_api_keys():
    """Lists metadata for all active dynamic API keys."""
    try:
        hashes = await redis_client._execute("SMEMBERS", "nancy:active_key_hashes") or []
        keys_list = []
        for h in hashes:
            meta = await redis_client.get_json(f"nancy:api_keys:{h}")
            if meta:
                keys_list.append(meta)
        return sorted(keys_list, key=lambda x: x.get("created_at", 0), reverse=True)
    except Exception:
        return []


@router.delete("/keys/revoke/{hashed_key}")
async def revoke_api_key(hashed_key: str):
    """Revokes and deletes an API key using its SHA-256 hash."""
    await redis_client.delete(f"nancy:api_keys:{hashed_key}")
    await redis_client._execute("SREM", "nancy:active_key_hashes", hashed_key)
    return {"success": True, "message": "API key revoked successfully."}

