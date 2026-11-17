import { redirect } from '@sveltejs/kit'

// Lead routing is no longer a page of its own: rules live in Organisation settings and are applied
// where leads are issued. Old links and bookmarks land on the rules tab.
export function load() {
	redirect(308, '/crm/organization?tab=routing')
}
