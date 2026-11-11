import type { FacebookLoginResponse } from './signup'

export const FACEBOOK_SDK_URL = 'https://connect.facebook.net/en_US/sdk.js'

interface FacebookSdk {
	init: (options: Record<string, unknown>) => void
	login: (
		callback: (response: FacebookLoginResponse) => void,
		options: Record<string, unknown>
	) => void
}

declare global {
	interface Window {
		FB?: FacebookSdk
		fbAsyncInit?: () => void
	}
}

let loading: Promise<FacebookSdk> | null = null
let initialisedFor = ''

/**
 * Load Meta's JavaScript SDK once and initialise it for this app. The promise is cached so
 * revisiting the page does not add a second script tag; a failed load can be retried.
 */
export function loadFacebookSdk(appId: string, version: string): Promise<FacebookSdk> {
	const key = `${appId}:${version}`
	if (loading && initialisedFor === key) return loading
	initialisedFor = key
	loading = new Promise<FacebookSdk>((resolve, reject) => {
		const ready = () => {
			const fb = window.FB
			if (!fb) return reject(new Error('Meta SDK did not start'))
			fb.init({ appId, autoLogAppEvents: true, xfbml: false, version })
			resolve(fb)
		}
		window.fbAsyncInit = ready
		if (window.FB) return ready()
		const script = document.createElement('script')
		script.src = FACEBOOK_SDK_URL
		script.async = true
		script.defer = true
		script.crossOrigin = 'anonymous'
		script.onerror = () => {
			loading = null
			script.remove()
			reject(new Error('Could not load the Meta sign-in script'))
		}
		document.head.append(script)
	})
	return loading
}
