import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js'
import type { LayoutLoad } from './$types';
import { PUBLIC_POSTHOG_KEY, PUBLIC_POSTHOG_HOST } from '$env/static/public';
import { auth, filters } from '$lib/api';

export const prerender = true;
export const ssr = false;

const PUBLIC_PATHS = ['/', '/login', '/auth/login', '/auth/callback', '/auth/no-org', '/auth/deactivated'];

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
    posthog.init(
      PUBLIC_POSTHOG_KEY,
      {
        api_host: PUBLIC_POSTHOG_HOST,
        defaults: '2025-05-24',
        person_profiles: 'identified_only',
      }
    );

    // Check auth for protected paths
    if (!isPublicPath(url.pathname)) {
      try {
        const user = await auth.me();
        // Identify user in PostHog
        posthog.identify(user.id, {
          email: user.email,
          first_name: user.first_name,
          last_name: user.last_name,
          organization_id: user.organization_id,
          organization_name: user.organization_name,
        });
        
        // Prefetch filter options for transactions pages (fire and forget)
        // These will be cached in queryClient and ready when user navigates
        queryClient.prefetchQuery({
          queryKey: ['filterOptions', 'sales'],
          queryFn: () => filters.sales({}),
          staleTime: Infinity,
        });
        queryClient.prefetchQuery({
          queryKey: ['filterOptions', 'rentals'],
          queryFn: () => filters.rentals({}),
          staleTime: Infinity,
        });
        
        return { queryClient, user };
      } catch {
        // Not authenticated, redirect to home
        redirect(302, '/');
      }
    }
  }

  return { queryClient, user: null };
};