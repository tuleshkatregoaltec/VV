import adapter from '@sveltejs/adapter-cloudflare'
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte'
import { cspDirectives } from './csp-directives.js'

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter(),
		env: {
			dir: '..'
		},
		// Pages are rendered by the Cloudflare Worker on every request (ssr = false only skips
		// component rendering), so SvelteKit can attach a fresh nonce to the CSP header. A static
		// _headers file could not allow the inline bootstrap script without 'unsafe-inline'.
		csp: {
			mode: 'auto',
			directives: cspDirectives
		}
	}
}

export default config
