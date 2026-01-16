import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js'
import type { LayoutLoad } from './$types';
import { env } from '$env/dynamic/public';
import { me, type BackendUser, get_session } from '$lib/api/auth';

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
            defaults: '2025-11-30',
          }
        );
        
        // Identify user on first app load if authenticated
        if (!isPublicPath(url.pathname)) {
          const session = await get_session();
          if (session) {
            try {
              const user = await me();
              posthog.identify(user.id, {
                email: user.email,
                first_name: user.first_name,
                last_name: user.last_name,
                organization_id: user.organization_id,
                organization_name: user.organization_name,
              });
            } catch {
              // User not authenticated, will be handled below
            }
          }
        }
      } catch (error) {
        console.warn('Failed to initialize PostHog:', error);
      }
    }

    // Check auth for protected paths
    if (!isPublicPath(url.pathname)) {
      // Check Supabase session first - this is synchronous from localStorage
      const session = await get_session();

      if (!session) {
        // No session, redirect immediately before loading anything
        redirect(302, '/auth');
      }

      // Have session, verify with backend
      try {
        const user = await me();
        return { queryClient, user };
      } catch {
        // Backend auth failed, redirect to auth page
        redirect(302, '/auth');
      }
    }
  }

  return { queryClient, user: null };
};