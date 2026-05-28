"""
Nancy HF Space — OpenAI-Compatible API Router.

Provides standard chat completion and models endpoints matching the OpenAI spec.
This allows any OpenAI-compatible client (e.g. LiteLLM, langchain, openai SDK)
to use Nancy as a drop-in replacement backbone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from config import settings
from core.auth import require_api_key
from core.queue import task_queue
from core.router import provider_router
from models.openai import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ErrorDetail,
    ErrorResponse,
    ModelInfo,
    ModelListResponse,
)
from models.task import Task, TaskStatus

logger = logging.getLogger("nancy.api")

def parse_tool_call_json(text: str) -> list[dict] | None:
    import json
    import re
    import uuid
    text = text.strip()

    # Resilient check for CALL: tool_name(...) format
    if "CALL:" in text:
        match = re.search(r"CALL:\s*(\w+)\((.*?)\)", text, re.DOTALL)
        if match:
            func_name = match.group(1)
            args_content = match.group(2)
            
            # Parse arguments in key="value" or key=value format
            args = {}
            arg_matches = re.findall(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s,]+))", args_content)
            for key, val1, val2, val3 in arg_matches:
                val = val1 or val2 or val3
                val_strip = val.strip()
                if val_strip.lower() == "true":
                    val = True
                elif val_strip.lower() == "false":
                    val = False
                else:
                    try:
                        if "." in val_strip:
                            val = float(val_strip)
                        else:
                            val = int(val_strip)
                    except:
                        pass
                args[key] = val
                
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            return [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps(args)
                }
            }]

    # Fallback to standard Markdown/JSON block parser
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
            
    if not (text.startswith("{") and "tool_calls" in text):
        return None
        
    try:
        data = json.loads(text)
        if "tool_calls" in data and isinstance(data["tool_calls"], list):
            validated = []
            for tc in data["tool_calls"]:
                if "name" in tc or ("function" in tc and "name" in tc["function"]):
                    func_name = tc.get("name") or tc["function"].get("name")
                    args = tc.get("arguments") or tc["function"].get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except:
                            pass
                    
                    call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
                    validated.append({
                        "id": call_id,
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": func_name,
                            "arguments": json.dumps(args) if isinstance(args, dict) else str(args)
                        }
                    })
            if validated:
                return validated
    except Exception as e:
        logger.warning("Failed to parse potential tool call JSON: %s", e)
    return None


router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    api_key: str = Depends(require_api_key),
):
    """
    OpenAI-Compatible Chat Completions Endpoint.
    Receives prompt, selects available provider, enqueues task for extension,
    and returns either a JSON response or an SSE stream.
    """
    # 1. Resolve request model to canonical provider
    requested_model = request.model
    provider = provider_router.resolve(requested_model)

    # Inject tool instructions into system prompt if requested
    if request.tools:
        # Build a clean, simplified human-readable tool definition list
        tool_specs = []
        for t in request.tools:
            func = t.get("function", {})
            name = func.get("name")
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_list = ", ".join(f"{k}: {v.get('type')}" for k, v in params.items())
            tool_specs.append(f"- {name}({param_list}): {desc}")
        
        specs_str = "\n".join(tool_specs)
        system_instruction = (
            "You are a helpful assistant with access to the following server-side tools. "
            "If you need to call a tool, you MUST respond ONLY with a clean tool execution instruction in this exact format:\n"
            "CALL: tool_name(arg1=\"value1\", arg2=\"value2\")\n"
            "and absolutely nothing else. Do not add any greeting, markdown formatting (like ```json), or explanatory text before or after the CALL. "
            "If no tool is needed or you are answering with the tool result, respond with standard conversational text.\n\n"
            "Here are the available tools:\n"
            f"{specs_str}"
        )
        messages_dump = [msg.model_dump() for msg in request.messages]
        if messages_dump and messages_dump[0]["role"] == "system":
            messages_dump[0]["content"] = system_instruction + "\n\n" + (messages_dump[0]["content"] or "")
        else:
            messages_dump.insert(0, {"role": "system", "content": system_instruction})
    else:
        messages_dump = [msg.model_dump() for msg in request.messages]

    # 2. Select available provider with routing / failover checks
    selected_provider = provider_router.select_provider(provider)
    if not selected_provider:
        error_detail = ErrorDetail(
            message="No healthy chatbot providers available at the moment.",
            type="service_unavailable",
            code="503",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(error=error_detail).model_dump(),
        )

    # 2b. Handle Hybrid Official API Routing
    if selected_provider.startswith("api-"):
        import httpx
        
        # Resolve target API URL and Authorization headers
        api_url = ""
        headers = {"Content-Type": "application/json"}
        
        if selected_provider == "api-mistral":
            api_url = "https://api.mistral.ai/v1/chat/completions"
            headers["Authorization"] = f"Bearer {settings.mistral_api_key}"
        elif selected_provider == "api-nvidia-nim":
            api_url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers["Authorization"] = f"Bearer {settings.nvidia_nim_api_key}"
        elif selected_provider == "api-deepseek":
            api_url = "https://api.deepseek.com/v1/chat/completions"
            headers["Authorization"] = f"Bearer {settings.deepseek_api_key}"
        elif selected_provider == "api-anthropic":
            api_url = "https://api.anthropic.com/v1/messages"
            headers["x-api-key"] = settings.anthropic_api_key
            headers["anthropic-version"] = "2023-06-01"
        elif selected_provider == "api-z-ai":
            api_url = "https://api.z.ai/v1/chat/completions"
            headers["Authorization"] = f"Bearer {settings.z_ai_api_key}"
            
        if not api_url:
            raise HTTPException(status_code=500, detail="API URL not configured for selected hybrid provider.")

        # Prepare request payload matching standard OpenAI schemas
        # Note: Anthropic uses a different schema, but we keep it simple for OpenAI compatible endpoints here
        payload = request.model_dump(exclude_none=True)
        # Override the model name in request to use the canonical official API model
        if selected_provider == "api-mistral":
            payload["model"] = "mistral-large-latest"
        elif selected_provider == "api-nvidia-nim":
            payload["model"] = "meta/llama3-70b-instruct"
        elif selected_provider == "api-deepseek":
            payload["model"] = "deepseek-chat"
        elif selected_provider == "api-anthropic":
            # Direct mapping from openai to anthropic messages format if needed, 
            # but for hybrid fallbacks we assume standard OpenAI endpoints or proxy models.
            payload["model"] = "claude-3-5-sonnet-latest"
        elif selected_provider == "api-z-ai":
            payload["model"] = "z-ai-latest"

        if request.stream:
            async def official_stream_generator() -> AsyncGenerator[dict, None]:
                async with httpx.AsyncClient() as client:
                    try:
                        async with client.stream("POST", api_url, headers=headers, json=payload, timeout=60.0) as resp:
                            if resp.status_code != 200:
                                yield {"data": f"[ERROR] Official API returned status code {resp.status_code}"}
                                yield {"data": "[DONE]"}
                                return
                            async for line in resp.aiter_lines():
                                if line.strip():
                                    yield {"data": line}
                    except Exception as e:
                        logger.error("Error in hybrid official API streaming: %s", e)
                        yield {"data": f"[ERROR] {str(e)}"}
                        yield {"data": "[DONE]"}
            return EventSourceResponse(official_stream_generator())
        else:
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(api_url, headers=headers, json=payload, timeout=60.0)
                    if resp.status_code != 200:
                        raise HTTPException(status_code=resp.status_code, detail=f"Official API Error: {resp.text}")
                    return JSONResponse(status_code=200, content=resp.json())
                except Exception as e:
                    logger.error("Error in hybrid official API: %s", e)
                    raise HTTPException(status_code=500, detail=f"Hybrid API call failed: {str(e)}")

    # 3. Create the internal Task
    session_id = None
    conversation_url = None
    action = "continue"

    if request.user:
        user_str = request.user.strip()
        if user_str.startswith("session:") or user_str.startswith("resume:"):
            parts = user_str.split(":", 1)
            target_sid = parts[1]
            from core.sessions import session_store
            session = await session_store.get_session(target_sid)
            if session:
                session_id = session.session_id
                conversation_url = session.conversation_url
                action = "resume_chat" if conversation_url else "new_chat"
                logger.info("Resuming session: %s (url: %s)", session_id, conversation_url)
        elif user_str.startswith("new_chat"):
            from core.sessions import session_store
            parts = user_str.split(":", 1)
            prov = parts[1] if len(parts) > 1 else selected_provider
            session = await session_store.create_session(provider=prov)
            session_id = session.session_id
            action = "new_chat"
            logger.info("Created new session: %s for provider: %s", session_id, prov)
        else:
            # Maybe it is a raw session_id
            from core.sessions import session_store
            session = await session_store.get_session(user_str)
            if session:
                session_id = session.session_id
                conversation_url = session.conversation_url
                action = "resume_chat" if conversation_url else "new_chat"
                logger.info("Resuming session via raw ID: %s", session_id)

    task = Task(
        provider=selected_provider,
        model=requested_model,
        messages=messages_dump,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=request.stream,
        session_id=session_id,
        conversation_url=conversation_url,
        action=action,
    )

    # 4. Submit to queue
    try:
        handle = await task_queue.submit_task(task)
    except asyncio.QueueFull:
        error_detail = ErrorDetail(
            message="Nancy task queue is currently full. Try again later.",
            type="rate_limit_error",
            code="429",
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=ErrorResponse(error=error_detail).model_dump(),
        )

    # 5. Handle Streaming Response (stream=True)
    if request.stream:
        async def stream_generator() -> AsyncGenerator[dict, None]:
            completion_id = handle.task.completion_id
            try:
                if request.tools:
                    buffer = []
                    is_potential_json = False
                    streamed_buffer = False

                    # Stream response chunks from the queue
                    async for chunk in task_queue.stream_chunks(handle):
                        if not buffer:
                            stripped = chunk.strip()
                            if stripped.startswith("{") or stripped.startswith("`"):
                                is_potential_json = True
                        
                        if is_potential_json and not streamed_buffer:
                            buffer.append(chunk)
                            if sum(len(c) for c in buffer) > 1536:
                                yield {
                                    "data": ChatCompletionChunk.first_chunk(
                                        completion_id, requested_model
                                    ).to_sse_data()
                                }
                                for b_chunk in buffer:
                                    yield {
                                        "data": ChatCompletionChunk.content_chunk(
                                            completion_id, requested_model, b_chunk
                                        ).to_sse_data()
                                    }
                                streamed_buffer = True
                        else:
                            if not streamed_buffer and not is_potential_json:
                                yield {
                                    "data": ChatCompletionChunk.first_chunk(
                                        completion_id, requested_model
                                    ).to_sse_data()
                                }
                                is_potential_json = True
                            yield {
                                "data": ChatCompletionChunk.content_chunk(
                                    completion_id, requested_model, chunk
                                ).to_sse_data()
                            }

                    # Flush or parse buffer
                    if is_potential_json and not streamed_buffer:
                        full_text = "".join(buffer)
                        tool_calls = parse_tool_call_json(full_text)
                        if tool_calls:
                            from models.openai import StreamChoice, DeltaContent
                            yield {
                                "data": ChatCompletionChunk(
                                    id=completion_id,
                                    model=requested_model,
                                    choices=[
                                        StreamChoice(
                                            index=0,
                                            delta=DeltaContent(
                                                role="assistant",
                                                tool_calls=tool_calls
                                            ),
                                            finish_reason="tool_calls"
                                        )
                                    ]
                                ).to_sse_data()
                            }
                        else:
                            yield {
                                "data": ChatCompletionChunk.first_chunk(
                                    completion_id, requested_model
                                ).to_sse_data()
                            }
                            for b_chunk in buffer:
                                yield {
                                    "data": ChatCompletionChunk.content_chunk(
                                        completion_id, requested_model, b_chunk
                                    ).to_sse_data()
                                }
                else:
                    yield {
                        "data": ChatCompletionChunk.first_chunk(
                            completion_id, requested_model
                        ).to_sse_data()
                    }
                    async for chunk in task_queue.stream_chunks(handle):
                        yield {
                            "data": ChatCompletionChunk.content_chunk(
                                completion_id, requested_model, chunk
                            ).to_sse_data()
                        }

                # Final chunk: finish reason
                yield {
                    "data": ChatCompletionChunk.final_chunk(
                        completion_id, requested_model, "stop"
                    ).to_sse_data()
                }

                # Raw [DONE] terminator
                yield {"data": "[DONE]"}

            except Exception as exc:
                logger.error("Error streaming chunks for task %s: %s", handle.task_id, exc)
                error_chunk = ChatCompletionChunk.final_chunk(
                    completion_id, requested_model, "length"
                )
                yield {"data": error_chunk.to_sse_data()}
                yield {"data": "[DONE]"}
            finally:
                # Release resources
                task_queue.cleanup_task(handle.task_id)

        return EventSourceResponse(stream_generator())

    # 6. Handle Non-streaming Blocking Response (stream=False)
    else:
        try:
            # Drain the queue to aggregate response chunks
            chunks = []
            async for chunk in task_queue.stream_chunks(handle):
                chunks.append(chunk)

            # Check if task failed or timed out
            if handle.task.status == TaskStatus.FAILED:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Chatbot provider failed: {handle.task.error}",
                )
            elif handle.task.status == TaskStatus.TIMED_OUT:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Chatbot provider timed out responding.",
                )

            full_content = "".join(chunks)
            if request.tools:
                tool_calls = parse_tool_call_json(full_content)
                if tool_calls:
                    from models.openai import Choice, ChoiceMessage
                    response = ChatCompletionResponse(
                        id=handle.task.completion_id,
                        model=requested_model,
                        choices=[
                            Choice(
                                index=0,
                                message=ChoiceMessage(
                                    role="assistant",
                                    content=None,
                                    tool_calls=tool_calls
                                ),
                                finish_reason="tool_calls"
                            )
                        ]
                    )
                    return response

            response = ChatCompletionResponse.from_content(
                content=full_content,
                model=requested_model,
            )
            response.id = handle.task.completion_id
            return response

        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error completing non-streaming task %s: %s", handle.task_id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Nancy internal server error: {exc}",
            )
        finally:
            # Release resources
            task_queue.cleanup_task(handle.task_id)


@router.get("/models", response_model=ModelListResponse)
async def list_models(api_key: str = Depends(require_api_key)):
    """
    List Available OpenAI Models.
    Maps to available providers configured in Nancy.
    """
    models = provider_router.get_available_models()
    model_infos = [ModelInfo(id=model) for model in models]
    return ModelListResponse(data=model_infos)


@router.get("/models/{model}", response_model=ModelInfo)
async def get_model(model: str, api_key: str = Depends(require_api_key)):
    """
    Retrieve specific model details.
    """
    models = provider_router.get_available_models()
    if model.lower() not in models:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model}' not found in Nancy configuration.",
        )
    return ModelInfo(id=model.lower())
