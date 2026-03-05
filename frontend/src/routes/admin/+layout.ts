import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { currentUser } from '$lib/stores/user.svelte';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ parent }) => {
    if (!browser) return {};

    // Wait for root layout to finish resolveUser() before checking role
    await parent();

    const user = currentUser.data;
    if (!user || user.role !== 'admin') {
        redirect(302, '/dashboard');
    }
    return { user };
};
