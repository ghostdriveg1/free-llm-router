/**
 * @fileoverview Server-Sent Events (SSE) stream parser.
 * Handles the SSE wire format: event, data, id, retry fields.
 * Supports multi-line data fields and incomplete chunk buffering.
 * @module utils/sse-parser
 */

/**
 * @typedef {Object} SSEEvent
 * @property {string} event - Event type (default: "message").
 * @property {string} data  - Concatenated data payload.
 * @property {string} id    - Last event ID.
 * @property {number|null} retry - Reconnection time in ms, if provided.
 */

/**
 * Stateful SSE parser. Feed it raw text chunks and it emits parsed events.
 */
export class SSEParser {
  constructor() {
    /** @private */ this._buffer = '';
    /** @private */ this._eventType = '';
    /** @private */ this._dataLines = [];
    /** @private */ this._lastId = '';
    /** @private */ this._retry = null;
  }

  /**
   * Feed a raw text chunk from the SSE stream.
   * @param {string} chunk - Raw text chunk (may contain partial lines).
   * @returns {SSEEvent[]} Array of fully parsed SSE events (may be empty).
   */
  feed(chunk) {
    this._buffer += chunk;
    const events = [];

    // Split on line endings (CR, LF, or CRLF)
    const lines = this._buffer.split(/\r\n|\r|\n/);

    // Last element might be an incomplete line — keep it in the buffer
    this._buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line === '') {
        // Empty line = dispatch event
        if (this._dataLines.length > 0) {
          events.push({
            event: this._eventType || 'message',
            data: this._dataLines.join('\n'),
            id: this._lastId,
            retry: this._retry,
          });
        }
        // Reset for next event
        this._eventType = '';
        this._dataLines = [];
        this._retry = null;
        continue;
      }

      // Ignore comments
      if (line.startsWith(':')) continue;

      // Parse field
      const colonIdx = line.indexOf(':');
      let field, value;

      if (colonIdx === -1) {
        // Field with no value
        field = line;
        value = '';
      } else {
        field = line.slice(0, colonIdx);
        // Skip optional single leading space after colon
        value = line[colonIdx + 1] === ' '
          ? line.slice(colonIdx + 2)
          : line.slice(colonIdx + 1);
      }

      switch (field) {
        case 'event':
          this._eventType = value;
          break;
        case 'data':
          this._dataLines.push(value);
          break;
        case 'id':
          // Per spec, id must not contain null
          if (!value.includes('\0')) {
            this._lastId = value;
          }
          break;
        case 'retry':
          // Must be all digits
          if (/^\d+$/.test(value)) {
            this._retry = parseInt(value, 10);
          }
          break;
        default:
          // Unknown fields are ignored per spec
          break;
      }
    }

    return events;
  }

  /**
   * Flush any remaining buffered data as a final event.
   * Call this when the stream ends.
   * @returns {SSEEvent[]} Zero or one final events.
   */
  flush() {
    // Process any remaining buffer content
    if (this._buffer) {
      // Feed the buffer with a newline to trigger line processing
      const remaining = this._buffer;
      this._buffer = '';
      return this.feed(remaining + '\n\n');
    }

    // Dispatch any pending data
    if (this._dataLines.length > 0) {
      const event = {
        event: this._eventType || 'message',
        data: this._dataLines.join('\n'),
        id: this._lastId,
        retry: this._retry,
      };
      this._eventType = '';
      this._dataLines = [];
      this._retry = null;
      return [event];
    }

    return [];
  }

  /**
   * Reset the parser to initial state.
   */
  reset() {
    this._buffer = '';
    this._eventType = '';
    this._dataLines = [];
    this._lastId = '';
    this._retry = null;
  }

  /** @returns {string} The last event ID seen. */
  get lastId() {
    return this._lastId;
  }
}

/**
 * Parse a complete SSE text blob into an array of events.
 * Convenience wrapper for one-shot parsing.
 * @param {string} text - Complete SSE text.
 * @returns {SSEEvent[]} Parsed events.
 */
export function parseSSE(text) {
  const parser = new SSEParser();
  const events = parser.feed(text);
  events.push(...parser.flush());
  return events;
}

/**
 * Extract JSON data from an SSE event's data field.
 * Returns null if the data is not valid JSON or is "[DONE]".
 * @param {SSEEvent} event - A parsed SSE event.
 * @returns {object|null} Parsed JSON or null.
 */
export function extractJSON(event) {
  const data = event?.data?.trim();
  if (!data || data === '[DONE]') return null;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}
