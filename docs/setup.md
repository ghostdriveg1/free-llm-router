# Nancy Setup Guide

Follow this guide to set up the Nancy FastAPI backend and the Chrome Extension relay.

---

## 1. Local FastAPI Server Setup

### Prerequisites
- Python 3.10 or higher installed.

### Installation
1. Navigate to the `hf-space` directory:
   ```bash
   cd hf-space
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows (cmd):
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running Locally
Start the server using `uvicorn`:
```bash
uvicorn main:app --host 127.0.0.1 --port 7860 --reload
```
The server will be available at `http://127.0.0.1:7860`. You can inspect the interactive OpenAPI documentation at `http://127.0.0.1:7860/docs`.

---

## 2. Deploying to Hugging Face Spaces

1. Create a free account on [Hugging Face](https://huggingface.co/).
2. Create a new Space:
   - **Owner**: Your username.
   - **Space Name**: `nancy` (or any custom name).
   - **SDK**: **Docker** (very important!).
   - **Template**: Blank.
   - **Visibility**: Public (or Private if you use strict API keys).
3. Clone the Space's Git repository or upload the files directly from the `hf-space` folder.
   - Ensure the `Dockerfile`, `requirements.txt`, `README.md`, `main.py`, `config.py`, and `core/` and `models/` and `routers/` folders are all uploaded to the root of the Space.
4. Set the following **Repository Secrets** in your Space settings (Settings → Variables and Secrets):
   - `NANCY_API_KEY`: A secure token for your agents (e.g. `your-super-agent-key`).
   - `NANCY_EXT_SECRET`: A secure token for extension communication (e.g. `your-super-extension-key`).
   - *Optional*: `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` (for caching and task survivability across container restarts).
5. The Space will automatically build the Docker image and deploy the server. Once running, your base URL will look like:
   `https://<your-username>-nancy.hf.space`

---

## 3. Chrome Extension Installation & Setup

1. Open Google Chrome.
2. Navigate to `chrome://extensions/`.
3. Enable **Developer mode** (toggle in the top-right corner).
4. Click **Load unpacked** in the top-left corner.
5. Select the `extension` folder inside this repository.
6. The extension is now loaded! Pin the "Nancy — Free LLM Router" extension to your toolbar.
7. Click the extension icon to open the **Control Dashboard** (Side Panel).
8. In the **Relay Config** card:
   - **Nancy Server URL**: Set to `http://127.0.0.1:7860` (for local testing) or your Hugging Face Space URL.
   - **Auth Token / API Key**: Enter the `NANCY_EXT_SECRET` value (matches the extension secret).
   - Click **Save Config** and then **Reconnect**. The connection status at the top will turn green and show **Connected**.

---

## 4. Hooking Up Your Agents

You can now configure any AI Agent framework (CrewAI, langchain, or custom scripts using the OpenAI SDK) to route queries through Nancy!

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<your-username>-nancy.hf.space/v1", # Or http://127.0.0.1:7860/v1
    api_key="your-super-agent-key" # Matches NANCY_API_KEY
)

# Call Nancy using any configured chatbot provider
response = client.chat.completions.create(
    model="gpt-4o", # Routes to ChatGPT
    messages=[
        {"role": "user", "content": "Explain quantum physics in three sentences."}
    ],
    stream=True # Fully supports Server-Sent Events (SSE) streaming!
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```
