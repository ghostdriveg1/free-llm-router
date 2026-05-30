/**
 * @fileoverview Fetch Interceptor content script (MAIN world).
 * Monkey-patches window.fetch to intercept raw API streams directly,
 * parsing SSE chunks for instant delta transmission, bypassed DOM delay.
 */

(function () {
  'use strict';

  let activeTaskId = null;
  let chatgptLastLength = 0;

  // Listen for the isolated observer setting the active Task ID
  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'NANCY_SET_TASK_ID') {
      activeTaskId = event.data.taskId;
      chatgptLastLength = 0; // Reset length for the new stream
    }
  });

  const TARGET_PATTERNS = [
    '/backend-api/conversation', // ChatGPT
    '/api/v0/chat/completion',    // DeepSeek
    '/api/chat/v2/completion',    // Kimi
    '/api/v1/chat/completions',   // Claude
    '/v1/chat/completions',       // NIM Portal & z.ai (OpenAI-compatible)
    '/api/chat',                  // z.ai alternative
    'streamGenerateContent',      // Gemini (Google AI Studio & gemini.google.com)
    'generateContent',            // Gemini non-streaming fallback
  ];

  function isTargetUrl(url) {
    return TARGET_PATTERNS.some(pattern => url.includes(pattern));
  }

  function detectProvider(url) {
    if (url.includes('openai.com') || url.includes('chatgpt.com')) return 'chatgpt';
    if (url.includes('gemini.google.com') || url.includes('google.com') || url.includes('generativelanguage.googleapis.com')) return 'gemini';
    if (url.includes('deepseek.com')) return 'deepseek';
    if (url.includes('kimi.moonshot.cn')) return 'kimi';
    if (url.includes('claude.ai')) return 'claude';
    if (url.includes('build.nvidia.com') || url.includes('nim.developer.nvidia.com')) return 'nim';
    if (url.includes('z.ai')) return 'zai';
    return null;
  }

  // ─── JSON Chunk Parsers ───────────────────────────────────────────────────
  function parseChatGPTChunk(json) {
    const parts = json?.message?.content?.parts;
    if (Array.isArray(parts) && parts.length > 0) {
      const fullText = parts[parts.length - 1];
      if (typeof fullText === 'string') {
        const delta = fullText.substring(chatgptLastLength);
        chatgptLastLength = fullText.length;
        return delta;
      }
    }
    return null;
  }

  function parseGeminiChunk(json) {
    // Gemini streamGenerateContent returns arrays: [{candidates:[{content:{parts:[{text:"..."}]}}]}]
    // Or sometimes a single object with the same structure.
    const candidates = json?.candidates;
    if (Array.isArray(candidates) && candidates.length > 0) {
      const parts = candidates[0]?.content?.parts;
      if (Array.isArray(parts) && parts.length > 0) {
        return parts.map(p => p.text || '').join('');
      }
    }
    return null;
  }

  function parseDeepSeekChunk(json) {
    return json?.choices?.[0]?.delta?.content || null;
  }

  function parseKimiChunk(json) {
    return json?.choices?.[0]?.delta?.content || null;
  }

  function parseClaudeChunk(json) {
    // Claude MV3 format delta
    if (json?.type === 'content_block_delta') {
      return json?.delta?.text || null;
    }
    return json?.completion || null; // Fallback to classic
  }

  function parseOpenAICompatibleChunk(json) {
    // Standard OpenAI streaming format - used by NIM, z.ai, and many others
    return json?.choices?.[0]?.delta?.content || null;
  }

  function extractDelta(line, provider) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return null;

    const dataValue = trimmed.substring(5).trim();
    if (dataValue === '[DONE]') return null;

    try {
      const json = JSON.parse(dataValue);
      switch (provider) {
        case 'chatgpt':
          return parseChatGPTChunk(json);
        case 'gemini':
          return parseGeminiChunk(json);
        case 'deepseek':
          return parseDeepSeekChunk(json);
        case 'kimi':
          return parseKimiChunk(json);
        case 'claude':
          return parseClaudeChunk(json);
        case 'nim':
        case 'zai':
          return parseOpenAICompatibleChunk(json);
        default:
          // Generic OpenAI-compatible fallback
          return parseOpenAICompatibleChunk(json) || null;
      }
    } catch {
      return null;
    }
  }

  // ─── window.fetch Monkey-Patch ─────────────────────────────────────────────
  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : input.url || '';
    
    if (activeTaskId && isTargetUrl(url)) {
      const provider = detectProvider(url);

      try {
        const response = await originalFetch(input, init);
        const contentType = response.headers.get('content-type') || '';
        
        if (response.body && contentType.includes('event-stream')) {
          const originalReader = response.body.getReader();
          const decoder = new TextDecoder();
          let sseBuffer = '';

          const customStream = new ReadableStream({
            async start(controller) {
              try {
                while (true) {
                  const { value, done } = await originalReader.read();
                  if (done) {
                    controller.close();
                    // Signal stream completion
                    window.postMessage({
                      type: 'NANCY_CHUNK',
                      taskId: activeTaskId,
                      chunk: '',
                      isDone: true,
                    }, '*');
                    break;
                  }

                  // Relay value back to page's original fetch caller
                  controller.enqueue(value);

                  // Extract text delta chunks for Nancy
                  const text = decoder.decode(value, { stream: true });
                  sseBuffer += text;

                  const lines = sseBuffer.split(/\r\n|\r|\n/);
                  sseBuffer = lines.pop() || ''; // Hold partial line

                  for (const line of lines) {
                    const delta = extractDelta(line, provider);
                    if (delta && delta.length > 0) {
                      window.postMessage({
                        type: 'NANCY_CHUNK',
                        taskId: activeTaskId,
                        chunk: delta,
                        isDone: false,
                      }, '*');
                    }
                  }
                }
              } catch (err) {
                controller.error(err);
              }
            }
          });

          return new Response(customStream, {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers,
          });
        }

        return response;
      } catch (err) {
        console.error('[Nancy/Interceptor] Fetch interception failed:', err);
        return originalFetch(input, init);
      }
    }

    return originalFetch(input, init);
  };
})();
