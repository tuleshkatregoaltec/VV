import { redirect } from '@sveltejs/kit';
import type { Handle } from '@sveltejs/kit';

const PUBLIC_PATHS = ['/landing'];

export const handle: Handle = async ({ event, resolve }) => {
	const { pathname } = event.url;

	if (pathname !== '/' && !PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
		redirect(301, '/');
	}

	return resolve(event);
};
