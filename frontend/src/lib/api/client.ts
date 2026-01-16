import { env } from '$env/dynamic/public';

import { get_access_token } from './auth';

export class ApiError extends Error {
    constructor(
        message: string,
        public status: number,
        public details?: unknown
    ) {
        super(message);
        this.name = 'ApiError';
    }
}

export interface RequestOptions {
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body?: unknown;
    headers?: Record<string, string>;
}

export async function api<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { method = 'GET', body, headers = {} } = options;

    // if access token available, add auth header. 
    const access_token = await get_access_token();
    if (access_token) {
        headers["Authorization"] = `Bearer ${access_token}`
    }

    const config: RequestInit = {
        method,
        credentials: 'include',
        headers: {
            ...headers,
        },
    };

    if (body !== undefined) {
        config.headers = {
            'Content-Type': 'application/json',
            ...config.headers,
        };
        config.body = JSON.stringify(body);
    }
    // @ts-ignore - Using window.fetch in CSR-only mode
    const res = await fetch(`${env.PUBLIC_API_BASE_URL}${endpoint}`, config);

    if (!res.ok) {
        let details: unknown;
        let message = res.statusText;

        try {
            const data = await res.json();
            details = data;
            if (Array.isArray(data.detail)) {
                message = data.detail.map((e: { msg: string }) => e.msg).join(', ');
            } else if (typeof data.detail === 'string') {
                message = data.detail;
            } else if (data.message) {
                message = data.message;
            }
        } catch {
            // Response wasn't JSON, use statusText
        }

        throw new ApiError(message, res.status, details);
    }

    if (res.status === 204) {
        return undefined as T;
    }

    return res.json();
}

export type StreamCallback = (chunk: string) => void;

/**
 * Stream SSE responses using fetch with ReadableStream.
 * Supports POST requests with request bodies.
 */
export function stream(
    endpoint: string,
    onChunk: StreamCallback,
    options: { method?: 'GET' | 'POST', body?: unknown } = {}
) {
    const { method = 'GET', body } = options;

    let abortController = new AbortController();
    let streamComplete = false;

    const config: RequestInit = {
        method,
        credentials: 'include',
        signal: abortController.signal,
        headers: {},
    };

    if (body !== undefined) {
        config.headers = {
            'Content-Type': 'application/json',
        };
        config.body = JSON.stringify(body);
    }

    // Start streaming
    // @ts-ignore - Using window.fetch in CSR-only mode
    fetch(`${env.PUBLIC_API_BASE_URL}${endpoint}`, config)
        .then(async (response) => {
            if (!response.ok) {
                if (response.status === 429) {
                    // Token limit exceeded
                    const errorData = await response.text().catch(() => 'Daily token limit exceeded');
                    throw new Error(`TOKEN_LIMIT_EXCEEDED: ${errorData}`);
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const reader = response.body?.pipeThrough(new TextDecoderStream()).getReader();
            if (!reader) {
                throw new Error('Response body is not readable');
            }

            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                // Add new data to buffer
                buffer += value;

                // Process complete SSE messages (separated by \n\n)
                const messages = buffer.split('\n\n');

                // Keep the last incomplete message in buffer
                buffer = messages.pop() || '';

                // Process complete messages
                for (const message of messages) {
                    if (!message.trim()) continue;

                    // Extract data from SSE format (data: {...})
                    const lines = message.split('\n');
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const data = line.slice(6); // Remove 'data: ' prefix

                            // Check if stream is complete
                            try {
                                const parsed = JSON.parse(data);
                                if (parsed.type === 'done') {
                                    streamComplete = true;
                                }
                            } catch {
                                // Not JSON, ignore
                            }

                            onChunk(data);
                        }
                    }
                }
            }
        })
        .catch((error) => {
            if (error.name === 'AbortError') {
                return; // Stream was intentionally closed
            }

            console.error('Stream error:', error);

            // Only send error if stream wasn't completed normally
            if (!streamComplete) {
                if (error.message.startsWith('TOKEN_LIMIT_EXCEEDED:')) {
                    onChunk(JSON.stringify({ type: 'error', error: 'token_limit_exceeded', details: error.message }));
                } else {
                    onChunk(JSON.stringify({ type: 'error', error: 'Stream connection failed' }));
                }
            }
        });

    return {
        close: () => {
            abortController.abort();
        }
    };
}

/**
 * Shorthand methods for common HTTP operations
 */
export const http = {
    get: <T>(endpoint: string) => api<T>(endpoint),
    post: <T>(endpoint: string, body?: unknown) => api<T>(endpoint, { method: 'POST', body }),
    put: <T>(endpoint: string, body?: unknown) => api<T>(endpoint, { method: 'PUT', body }),
    patch: <T>(endpoint: string, body?: unknown) => api<T>(endpoint, { method: 'PATCH', body }),
    delete: <T>(endpoint: string) => api<T>(endpoint, { method: 'DELETE' }),
};
