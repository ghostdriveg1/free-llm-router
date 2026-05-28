---
title: Ultron Test Agent
emoji: 🤖
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Ultron Lite — Agent Testing Web Interface

An interactive, glassmorphic dark-mode web application that runs a standard ReAct 
agent loop with tool-calling capabilities. Exposes tools directly to the agent
and streams thoughts, tool executions, and responses live to a chat interface.

### Running Locally
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 7860 --reload
```
