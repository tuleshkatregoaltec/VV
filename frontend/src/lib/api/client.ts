import { PUBLIC_API_BASE_URL } from '$env/static/public';

export class ApiError extends Error {
    constructor(message: string, public status: number) {
        super(message);
    }
}

export async function api<T>(endpoint: string): Promise<T> {
    const res = await fetch(`${PUBLIC_API_BASE_URL}${endpoint}`, {
        credentials: 'include'
    });
    if (!res.ok) throw new ApiError(res.statusText, res.status);
    return res.json();
}
