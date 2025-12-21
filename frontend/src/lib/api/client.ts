import { PUBLIC_API_BASE_URL } from '$env/static/public';

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
    const res = await fetch(`${PUBLIC_API_BASE_URL}${endpoint}`, config);

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
 * Stream SSE responses using native EventSource.
 * Note: EventSource only supports GET requests.
 */
export function stream(endpoint: string, onChunk: StreamCallback) {
    const eventSource = new EventSource(`${PUBLIC_API_BASE_URL}${endpoint}`, {
        withCredentials: true
    });

    let streamComplete = false;

    eventSource.onmessage = (event) => {
        const data = event.data;

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
    };

    eventSource.onerror = (error) => {
        console.error('EventSource error:', error);
        eventSource.close();

        // Only send error if stream wasn't completed normally
        if (!streamComplete) {
            onChunk(JSON.stringify({type: 'error', error: 'Stream connection failed'}));
        }
    };

    return {
        close: () => eventSource.close()
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
