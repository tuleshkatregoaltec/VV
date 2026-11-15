/**
 * Scraped data supplies outbound links. Only plain http(s) URLs may reach an href;
 * `javascript:`, `data:` and similar schemes would run or render on click.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
	if (!value || [...value].some((character) => character.charCodeAt(0) <= 32)) return null
	try {
		const { protocol } = new URL(value)
		return protocol === 'http:' || protocol === 'https:' ? value : null
	} catch {
		return null
	}
}
