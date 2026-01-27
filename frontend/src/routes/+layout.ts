import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js'
import type { LayoutLoad } from './$types';
import { env } from '$env/dynamic/public';
import { get_session, me } from '$lib/api/auth';
import { currentUser, setUser } from '$lib/stores/user.svelte';

export const prerender = false;
export const ssr = false;

const PUBLIC_PATHS = ['/', '/landing-new', '/auth', '/auth/reset-password', '/auth/no-org', '/auth/deactivated'];

function isPublicPath(pathname: string): boolean {
  return pathname === '/' || PUBLIC_PATHS.slice(1).some((p) => pathname.startsWith(p));
}

export const load: LayoutLoad = async ({ url }) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        enabled: browser, // Disable queries on server
        staleTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
      },
    },
  });

  if (browser) {
    // Initialize PostHog if credentials are available and not already initialized
    if (env.PUBLIC_POSTHOG_KEY && env.PUBLIC_POSTHOG_HOST && !posthog.__loaded) {
      try {
        posthog.init(
          env.PUBLIC_POSTHOG_KEY,
          {
            api_host: env.PUBLIC_POSTHOG_HOST,
            ui_host: 'https://eu.posthog.com',
            defaults: '2025-11-30',
          }
        );
      } catch (error) {
        console.warn('Failed to initialize PostHog:', error);
      }
    }

    if (!isPublicPath(url.pathname)) {
      const session = await get_session();

      if (!session) {
        redirect(302, '/auth');
      }

      // CRITICAL: Block and resolve user if store empty
      // This prevents UI flash on protected routes
      let user = currentUser.data;

      if (!user) {
        try {
          user = await me();
          setUser(user); // Cache in store
        } catch (err) {
          // API error - redirect to auth
          redirect(302, '/auth');
        }
      }

      // Check organization membership
      if (!user.organization_id) {
        // No organization - redirect to onboarding
        redirect(302, '/onboarding/organization-setup');
      }

      return { queryClient };
    }
  }

  return { queryClient };
};