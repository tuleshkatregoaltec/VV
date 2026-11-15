/**
 * Backend and scraped data can carry links. Only absolute http(s) URLs may reach an href, so a
 * `javascript:`, `data:` or similar value stored in a record can never run in the page.
 */
export function safeExternalHref(value: unknown): string | null {
	if (typeof value !== 'string') return null
	const trimmed = value.trim()
	// A scheme-relative or relative URL is not a deliberate external link.
	if (!/^https?:\/\//i.test(trimmed)) return null
	try {
		const url = new URL(trimmed)
		if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
		if (url.username || url.password || !url.hostname) return null
		return url.href === trimmed || url.href === `${trimmed}/` ? trimmed : url.href
	} catch {
		return null
	}
}
