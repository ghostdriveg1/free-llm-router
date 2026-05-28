"""
Nancy HF Space — Executable Tools Core.

Provides standard server-side tools that can be exposed to AI agents (like Ultron)
and executed locally on the FastAPI backend.
"""

from __future__ import annotations

import logging
import json
from typing import Any, Callable

from core.sessions import session_store

logger = logging.getLogger("nancy.tools")

# ─── Built-in Tools Implementation ──────────────────────────────────────────

async def web_search(query: str) -> str:
    """
    Search the web for the given query using DuckDuckGo Search.
    
    Args:
        query: The search query string.
        
    Returns:
        A text summary of top search results.
    """
    logger.info("Executing web search: '%s'", query)
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                return "No search results found."
            
            output = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No Title")
                href = r.get("href", "#")
                body = r.get("body", "")
                output.append(f"[{i}] {title}\nURL: {href}\nSnippet: {body}\n")
            return "\n".join(output)
    except Exception as e:
        logger.error("Web search failed for query '%s': %s", query, e)
        return f"Error executing web search: {str(e)}"


async def nancy_new_chat(provider: str, system_prompt: str | None = None, title: str | None = None) -> str:
    """
    Start a brand new conversation session with the specified provider.
    
    Args:
        provider: Target chatbot provider (e.g. 'chatgpt', 'gemini', 'deepseek').
        system_prompt: Optional initial prompt or instructions to prep in the new chat.
        title: Optional custom session title.
        
    Returns:
        JSON string indicating new session details.
    """
    logger.info("Creating new session for provider '%s'", provider)
    try:
        session = await session_store.create_session(
            provider=provider,
            title=title,
            system_prompt=system_prompt
        )
        return json.dumps({
            "status": "success",
            "message": "New chat session created successfully. To use it, pass the session_id in the 'user' field in future completions.",
            "session_id": session.session_id,
            "provider": session.provider,
            "title": session.title
        })
    except Exception as e:
        logger.error("Failed to create new session: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


async def nancy_resume_chat(session_id: str) -> str:
    """
    Retrieve details of a saved chat session to resume it.
    
    Args:
        session_id: The UUID of the session.
        
    Returns:
        JSON string with session details.
    """
    logger.info("Resuming session: '%s'", session_id)
    try:
        session = await session_store.get_session(session_id)
        if not session:
            return json.dumps({"status": "error", "message": f"Session {session_id} not found."})
        return json.dumps({
            "status": "success",
            "session_id": session.session_id,
            "provider": session.provider,
            "title": session.title,
            "conversation_url": session.conversation_url,
            "system_prompt": session.system_prompt,
            "message_count": session.message_count,
            "status_state": session.status
        })
    except Exception as e:
        logger.error("Failed to resume session '%s': %s", session_id, e)
        return json.dumps({"status": "error", "message": str(e)})


async def nancy_list_sessions(provider: str | None = None) -> str:
    """
    List all tracked conversation sessions, optionally filtered by provider.
    
    Args:
        provider: Optional filter (e.g. 'chatgpt', 'gemini').
        
    Returns:
        JSON string with session list.
    """
    logger.info("Listing sessions. Filter: %s", provider)
    try:
        sessions = await session_store.list_sessions(provider=provider)
        serialized = [s.to_dict() for s in sessions]
        return json.dumps({
            "status": "success",
            "sessions": serialized
        })
    except Exception as e:
        logger.error("Failed to list sessions: %s", e)
        return json.dumps({"status": "error", "message": str(e)})


# ─── Tool Registry & Dispatcher ──────────────────────────────────────────────

class ToolRegistry:
    """Registry mapping tool names to their async handlers and schemas."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._schemas: list[dict[str, Any]] = []

        # Register our built-in tools
        self.register("web_search", web_search, {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for real-time information or questions requiring search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text."
                        }
                    },
                    "required": ["query"]
                }
            }
        })

        self.register("nancy_new_chat", nancy_new_chat, {
            "type": "function",
            "function": {
                "name": "nancy_new_chat",
                "description": "Start a brand new conversation session with a chatbot provider.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Target provider key, e.g. 'chatgpt', 'gemini', 'deepseek'."
                        },
                        "system_prompt": {
                            "type": "string",
                            "description": "Optional instructions/rules to prepend to this conversation."
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional human-readable title."
                        }
                    },
                    "required": ["provider"]
                }
            }
        })

        self.register("nancy_resume_chat", nancy_resume_chat, {
            "type": "function",
            "function": {
                "name": "nancy_resume_chat",
                "description": "Retrieve information on an existing saved chat session by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The session ID UUID."
                        }
                    },
                    "required": ["session_id"]
                }
            }
        })

        self.register("nancy_list_sessions", nancy_list_sessions, {
            "type": "function",
            "function": {
                "name": "nancy_list_sessions",
                "description": "List all active saved conversation sessions in Nancy.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Optional chatbot provider to filter by."
                        }
                    }
                }
            }
        })

    def register(self, name: str, handler: Callable[..., Any], schema: dict[str, Any]) -> None:
        """Register a new tool."""
        self._handlers[name] = handler
        self._schemas.append(schema)

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get the schemas of all registered tools."""
        return self._schemas

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name with arguments."""
        handler = self._handlers.get(name)
        if not handler:
            raise ValueError(f"Tool '{name}' is not registered.")
        
        try:
            return await handler(**arguments)
        except Exception as e:
            logger.error("Error executing tool '%s': %s", name, e)
            return f"Execution error: {str(e)}"


# Module-level singleton registry
tool_registry = ToolRegistry()
