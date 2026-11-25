/**
 * What the chat shows for a failed turn. The server sends a stable `code` (backend
 * app/chat/errors.py); the stream client adds its own codes for HTTP refusals before the
 * stream and for connection problems. Messages are chosen here by code, never parsed from text.
 */

export interface ChatErrorEvent {
	type?: string
	code?: string
	error?: string
	retryable?: boolean
	reference?: string
	resets_at?: string
	tokens_used?: number
	daily_limit?: number
}

export interface ChatErrorView {
	message: string
	/** Sending the same message again is reasonable (nothing is left running). */
	retry: boolean
	/** The turn may still finish on the server: reload the conversation instead of resending. */
	reloadConversation: boolean
	/** The daily allowance is used up: the limit dialog explains it. */
	dailyLimit: boolean
}

const GENERIC = 'The assistant could not complete this request. Please try again.'

const MESSAGES: Record<string, { message: string; retry?: boolean }> = {
	conversation_not_found: { message: 'This conversation no longer exists. Start a new one.' },
	assistant_disabled: { message: 'The assistant is not enabled for your account yet.' },
	account_unavailable: { message: 'Your account could not be verified. Please sign in again.' },
	turn_in_progress: {
		message: 'Another answer is still being prepared. Wait for it to finish, then send again.',
		retry: true
	},
	service_busy: { message: 'The assistant is busy right now. Try again in a moment.', retry: true },
	insufficient_allowance: {
		message: "Not enough of today's assistant allowance is left to start another answer."
	},
	daily_limit_reached: { message: "You have used today's assistant allowance." },
	turn_budget_exceeded: {
		message:
			'This question needed more research steps than one answer allows. Ask about one area, project or record at a time.'
	},
	provider_rate_limited: {
		message: 'The assistant service is busy right now. Try again in a minute.',
		retry: true
	},
	provider_unavailable: {
		message: 'The assistant service is temporarily unavailable. Try again shortly.',
		retry: true
	},
	provider_timeout: {
		message: 'The answer took too long and was stopped. Try again, or ask a narrower question.',
		retry: true
	},
	provider_invalid_response: {
		message: 'The assistant service returned an unusable answer. Please try again.',
		retry: true
	},
	internal_error: { message: GENERIC, retry: true },
	// Refusals before the stream starts (HTTP status, no server code).
	session_expired: { message: 'Your session has expired. Please sign in again.' },
	access_denied: {
		message: "Your account or organization can't use the assistant right now."
	},
	invalid_request: {
		message: "This message couldn't be sent. Shorten it or rephrase it, then try again."
	},
	server_unavailable: {
		message: "The assistant couldn't be reached. Check your connection and try again.",
		retry: true
	}
}

/** Connection problems after the request was sent: the server may still be answering. */
const STILL_RUNNING: Record<string, string> = {
	stream_interrupted:
		'The connection was interrupted before the answer arrived. It may still finish; the conversation will reload shortly.',
	network_error:
		'The connection to the assistant was lost. The answer may still finish; the conversation will reload shortly.'
}

function resetTime(iso: string | undefined): string | null {
	if (!iso) return null
	const at = new Date(iso)
	if (Number.isNaN(at.getTime())) return null
	return at.toLocaleString('en-GB', {
		timeZone: 'Asia/Dubai',
		day: 'numeric',
		month: 'short',
		hour: '2-digit',
		minute: '2-digit'
	})
}

export function describeChatError(event: ChatErrorEvent): ChatErrorView {
	const code = event.code ?? (event.error === 'token_limit_exceeded' ? 'daily_limit_reached' : '')
	if (code in STILL_RUNNING) {
		return {
			message: STILL_RUNNING[code],
			retry: false,
			reloadConversation: true,
			dailyLimit: false
		}
	}
	const known = MESSAGES[code]
	let message = known?.message ?? GENERIC
	if (code === 'daily_limit_reached' || code === 'insufficient_allowance') {
		const usage =
			typeof event.tokens_used === 'number' && typeof event.daily_limit === 'number'
				? ` (${event.tokens_used.toLocaleString('en-US')} of ${event.daily_limit.toLocaleString('en-US')} tokens used)`
				: ''
		const resets = resetTime(event.resets_at)
		message = `${message.replace(/\.$/, '')}${usage}.${resets ? ` It resets ${resets} Dubai time.` : ''}`
	}
	if (code === 'internal_error' && event.reference) {
		message = `${message} (Reference ${event.reference})`
	}
	return {
		message,
		retry: Boolean(known?.retry),
		reloadConversation: false,
		dailyLimit: code === 'daily_limit_reached'
	}
}
