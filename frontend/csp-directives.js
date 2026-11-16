// Content-Security-Policy for the SvelteKit app, consumed by `kit.csp` in svelte.config.js.
// SvelteKit adds a per-response nonce for its own bootstrap script and for app.html's theme script.
//
// Every origin below is one the app really loads from or connects to:
//  - api-pilot.vitevue.com: backend API (PUBLIC_API_BASE_URL, wrangler.jsonc)
//  - fxszmyazeonmxxeixzoh.supabase.co: Supabase Auth (PUBLIC_AUTH_BASE_URL)
//  - basemaps.cartocdn.com and its tile/glyph/sprite subdomains: MapLibre basemap style
//  - fonts.googleapis.com / fonts.gstatic.com: Inter (app.css)
//  - connect.facebook.net, facebook.com: Meta Embedded Signup SDK on /crm/whatsapp
//  - eu.i.posthog.com / eu-assets.i.posthog.com: PostHog, dormant until PUBLIC_POSTHOG_KEY is set
// When PUBLIC_API_BASE_URL or PUBLIC_AUTH_BASE_URL moves to another host, change it here too.
//
// The API and auth origins configured in the environment that starts the server or build are
// allowed as well, so local development (http://localhost:8000, a LAN auth server) can sign in.
// Production builds get these values at runtime from wrangler.jsonc, so their policy is unchanged.

const API_ORIGIN = 'https://api-pilot.vitevue.com'
const SUPABASE_ORIGIN = 'https://fxszmyazeonmxxeixzoh.supabase.co'

/** @param {string | undefined} value */
function originOf(value) {
	try {
		return value ? new URL(value).origin : null
	} catch {
		return null
	}
}

/** @param {Record<string, string | undefined>} env */
export function configuredOrigins(env) {
	return [originOf(env.PUBLIC_API_BASE_URL), originOf(env.PUBLIC_AUTH_BASE_URL)].filter(
		/** @returns {origin is string} */ (origin) => origin !== null
	)
}

const CONFIGURED = configuredOrigins(typeof process === 'undefined' ? {} : process.env).filter(
	(origin) => origin !== API_ORIGIN && origin !== SUPABASE_ORIGIN
)
// Upgrading would turn a configured http:// API or auth server into an unreachable https:// one.
const INSECURE_CONFIGURED = CONFIGURED.some((origin) => origin.startsWith('http:'))
const CARTO = ['https://basemaps.cartocdn.com', 'https://*.basemaps.cartocdn.com']
const POSTHOG = ['https://eu.i.posthog.com', 'https://eu-assets.i.posthog.com']
const FACEBOOK_SCRIPTS = ['https://connect.facebook.net']
const FACEBOOK = ['https://*.facebook.com', 'https://connect.facebook.net']

/** @type {Record<string, string[] | true>} */
export const cspDirectives = {
	'default-src': ['self'],
	'script-src': ['self', ...FACEBOOK_SCRIPTS, ...POSTHOG],
	// Svelte transitions, MapLibre popups and the markup in several pages set inline style attributes.
	'style-src': ['self', 'unsafe-inline', 'https://fonts.googleapis.com'],
	'font-src': ['self', 'data:', 'https://fonts.gstatic.com'],
	// Listing photos, news thumbnails (signed S3 URLs) and basemap tiles come from many https hosts.
	'img-src': ['self', 'data:', 'blob:', 'https:'],
	'connect-src': [
		'self',
		API_ORIGIN,
		SUPABASE_ORIGIN,
		...CONFIGURED,
		...CARTO,
		...POSTHOG,
		...FACEBOOK
	],
	// MapLibre runs its tile workers from a blob: URL.
	'worker-src': ['self', 'blob:'],
	'child-src': ['self', 'blob:'],
	'frame-src': FACEBOOK,
	'media-src': ['self', 'blob:', 'data:'],
	'manifest-src': ['self'],
	'object-src': ['none'],
	'base-uri': ['self'],
	'form-action': ['self'],
	'frame-ancestors': ['none'],
	...(INSECURE_CONFIGURED ? {} : { 'upgrade-insecure-requests': true })
}
