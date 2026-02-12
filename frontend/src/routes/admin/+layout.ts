import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { currentUser } from '$lib/stores/user.svelte';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async () => {
    if (!browser) return {};

    const user = currentUser.data;
    if (!user || user.role !== 'admin') {
        error(403, 'Admin access required');
    }
    return { user };
};
