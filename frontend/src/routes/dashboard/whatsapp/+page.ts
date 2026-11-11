import { redirect } from '@sveltejs/kit'

// The review inbox moved into the one WhatsApp page; keep old links and bookmarks working.
export function load({ url }) {
	redirect(307, `/crm/whatsapp${url.search}`)
}
