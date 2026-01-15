import { env } from '$env/dynamic/public';

import { AuthClient } from '@supabase/auth-js';

const client = new AuthClient({
    url: `${env.PUBLIC_AUTH_BASE_URL}`,
    storageKey: "authentication",
    detectSessionInUrl: true,
    persistSession: true,

});

export async function get_access_token(): Promise<string | undefined> {
    const res = await client.getSession();

    if (res.data && !res.error) {
        return res.data.session?.access_token;
    }
};

/**
 * Login with email/password, storing into localstorage if successful.
 * 
 * @param email Email address
 * @param password Password
 * @returns {boolean} success
 */
export async function login_with_email_pass(email: string, password: string) {
    const res = await client.signInWithPassword({ email, password })

    if (!res.error && res.data) {
        // success
        return true;
    }

    // failure
    return false;
}