import { browser } from '$app/environment';
import { QueryClient } from '@tanstack/svelte-query';
import posthog from 'posthog-js'
import type { LayoutLoad } from './$types';
import { PUBLIC_POSTHOG_KEY, PUBLIC_POSTHOG_HOST } from '$env/static/public';

export const prerender = true;
export const ssr = false;


export const load: LayoutLoad = async () => {
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
        person_profiles: 'identified_only', // change to only authenticated users
      }
    )
  }


  return { queryClient };
};