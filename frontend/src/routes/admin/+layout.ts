import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { auth } from '$lib/api/auth';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async () => {
    if (!browser) return {};

    try {
        const user = await auth.me();
        if (user.role !== 'admin') {
            error(403, 'Admin access required');
        }
        return { user };
    } catch (e) {
        // Not authenticated or API error
        error(403, 'Admin access required');
    }
};
