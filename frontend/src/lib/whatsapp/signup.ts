/**
 * Meta Embedded Signup, client side.
 *
 * Meta reports the result through two separate channels: FB.login's callback carries a
 * short-lived auth code (about 30 seconds), and a window "message" from facebook.com carries the
 * phone number and account ids. They can arrive in either order, so the collector waits for both
 * and hands them over together the moment the second one lands.
 */

export interface SignupResult {
	code: string
	event: string
	phone_number_id: string
	waba_id: string
	business_id: string | null
}

export type StopKind = 'cancelled' | 'error' | 'timeout'

export interface FacebookLoginResponse {
	status?: string
	authResponse?: { code?: string } | null
}

export interface MessageLike {
	origin: string
	data: unknown
}

/** How long to wait for the second half once the first has arrived. */
export const SIGNUP_WAIT_MS = 20_000

const FINISH_EVENTS = new Set(['FINISH', 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING'])

export function isFacebookOrigin(origin: string): boolean {
	try {
		const url = new URL(origin)
		return (
			url.protocol === 'https:' &&
			(url.hostname === 'facebook.com' || url.hostname.endsWith('.facebook.com'))
		)
	} catch {
		return false
	}
}

function parseMessage(data: unknown): Record<string, unknown> | null {
	let value = data
	if (typeof value === 'string') {
		try {
			value = JSON.parse(value)
		} catch {
			return null
		}
	}
	return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

const text = (value: unknown): string | null =>
	typeof value === 'string' && value.trim() ? value : null

export function createSignupCollector(handlers: {
	onComplete: (result: SignupResult) => void
	onStop: (kind: StopKind, message: string) => void
	waitMs?: number
}) {
	let code: string | null = null
	let ids: Omit<SignupResult, 'code'> | null = null
	let finished = false
	let timer: ReturnType<typeof setTimeout> | undefined

	function end() {
		finished = true
		clearTimeout(timer)
	}

	function stop(kind: StopKind, message: string) {
		if (finished) return
		end()
		handlers.onStop(kind, message)
	}

	function settle() {
		if (finished) return
		if (code && ids) {
			end()
			handlers.onComplete({ code, ...ids })
			return
		}
		if (code || ids) {
			clearTimeout(timer)
			timer = setTimeout(
				() =>
					stop(
						'timeout',
						'Meta did not finish the connection in time. Close the Meta window and try again.'
					),
				handlers.waitMs ?? SIGNUP_WAIT_MS
			)
		}
	}

	return {
		handleLogin(response: FacebookLoginResponse | null | undefined) {
			if (finished) return
			const received = text(response?.authResponse?.code)
			if (!received) {
				stop(
					'cancelled',
					'The connection was cancelled, so nothing was connected. You can start again whenever you are ready.'
				)
				return
			}
			code = received
			settle()
		},

		handleMessage(event: MessageLike) {
			if (finished || !isFacebookOrigin(event.origin)) return
			const message = parseMessage(event.data)
			if (!message || message.type !== 'WA_EMBEDDED_SIGNUP') return
			const kind = text(message.event)
			const data = (message.data && typeof message.data === 'object' ? message.data : {}) as Record<
				string,
				unknown
			>

			if (kind === 'CANCEL') {
				stop(
					'cancelled',
					'The connection was cancelled, so nothing was connected. You can start again whenever you are ready.'
				)
				return
			}
			if (kind === 'ERROR') {
				const detail = text(data.error_message)
				stop(
					'error',
					`Meta reported a problem${detail ? `: ${detail}` : '.'} Nothing was connected.`
				)
				return
			}
			if (!kind || !FINISH_EVENTS.has(kind)) {
				if (kind?.startsWith('FINISH')) {
					stop(
						'error',
						'Meta finished without a phone number. Connect the phone number of your WhatsApp Business app.'
					)
				}
				return
			}
			const phone = text(data.phone_number_id)
			const waba = text(data.waba_id)
			if (!phone || !waba) {
				stop(
					'error',
					'Meta did not return a phone number. Nothing was connected; please try again.'
				)
				return
			}
			ids = {
				event: kind,
				phone_number_id: phone,
				waba_id: waba,
				business_id: text(data.business_id)
			}
			settle()
		},

		/** Stop listening; nothing is reported afterwards. */
		dispose() {
			end()
		}
	}
}

export function describeCompleteError(status: number): string {
	switch (status) {
		case 400:
			return 'That attempt took too long and expired. Start again.'
		case 403:
			return 'Meta connected the number, but it is not available to Vitevue yet. Try again, and contact support if it keeps happening.'
		case 409:
			return 'This number is already connected, to your account or to another one. Use a different number, or contact support.'
		case 422:
			return 'Connect the phone number of your existing WhatsApp Business app, not a new standalone account.'
		case 502:
			return 'Meta did not accept the connection. Start again in a moment.'
		case 503:
			return 'WhatsApp connection is being set up. Check back soon.'
		case 0:
			return 'Could not reach Vitevue. Check your internet connection and try again.'
		default:
			return 'Something went wrong while connecting. Try again.'
	}
}
