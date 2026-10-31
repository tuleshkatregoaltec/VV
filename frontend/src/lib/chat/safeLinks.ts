/** Model text may link only to application routes, without outbound tracking URLs. */
export function safeChatHref(href: string, origin: string): string | null {
	if (!href || [...href].some((character) => character.charCodeAt(0) <= 32 || character === '\\'))
		return null
	try {
		const url = new URL(href, origin)
		if (url.origin !== origin || !['http:', 'https:'].includes(url.protocol)) return null
		if (
			!/^\/(chat|crm|analytics|projects|transactions|radar|dashboard|feasibility)(\/|$)/.test(
				url.pathname
			)
		)
			return null
		return `${url.pathname}${url.search}${url.hash}`
	} catch {
		return null
	}
}
