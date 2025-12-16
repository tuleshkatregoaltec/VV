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
            // Handle FastAPI validation errors
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

    // Handle 204 No Content
    if (res.status === 204) {
        return undefined as T;
    }

    return res.json();
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
