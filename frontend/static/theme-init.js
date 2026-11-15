// Applies the saved theme before first paint. Loaded as an external script so the page's
// Content-Security-Policy needs no inline-script allowance (prerendered pages cannot use nonces).
;(() => {
	try {
		const stored = JSON.parse(localStorage.getItem('vitevue-preferences') || '{}')
		const preference = ['light', 'dark', 'system'].includes(stored.theme)
			? stored.theme
			: 'system'
		const resolved =
			preference === 'system'
				? window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: preference
		document.documentElement.dataset.theme = resolved
		document.documentElement.dataset.themePreference = preference
		document.documentElement.style.colorScheme = resolved
	} catch {
		const resolved = window.matchMedia('(prefers-color-scheme: dark)').matches
			? 'dark'
			: 'light'
		document.documentElement.dataset.theme = resolved
		document.documentElement.dataset.themePreference = 'system'
		document.documentElement.style.colorScheme = resolved
	}
})()
