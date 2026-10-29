import { redirect } from '@sveltejs/kit'

/** v2 (7 Oct) dropped the Connections page; Manager › Connectors (28 Oct) replaces it. */
export function load() {
	redirect(307, '/crm/connectors')
}
