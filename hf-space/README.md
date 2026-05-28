---
title: Nancy
emoji: 🔀
colorFrom: purple
colorTo: blue
sdk: docker
pinned: false
license: mit
app_port: 7860
---

# Nancy — Free LLM Router

Nancy converts free chatbot web UIs into OpenAI-compatible APIs.

## Architecture

- **API Layer**: OpenAI-compatible `/v1/chat/completions` and `/v1/models`
- **Task Queue**: Async task queue bridges API requests to browser extension
- **Extension Relay**: Chrome extension connects via SSE, executes tasks in real browser tabs
- **Provider Router**: Circuit breaker + fallback chains across multiple free LLM providers

## Usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://your-space.hf.space/v1",
    api_key="your-nancy-api-key",
)

response = client.chat.completions.create(
    model="chatgpt",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```
