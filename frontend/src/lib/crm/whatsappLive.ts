import type { QueryKey } from '@tanstack/svelte-query'

/**
 * Connectors › WhatsApp, live: the backend says which chat changed (a new message, a delivery
 * status) and the screen refetches it through the usual endpoints. The socket carries no message
 * content, so nothing here bypasses the access checks the endpoints already make.
 */

/** Close codes after which retrying cannot help: signed out, or no access. */
const FINAL = new Set([4401, 4403])
const MAX_BACKOFF_MS = 30_000

/** `http://localhost:8000` → `ws://localhost:8000/api/v1/crm/whatsapp/live` */
export const liveUrl = (apiBase: string) =>
	`${apiBase.replace(/^http/, 'ws')}/api/v1/crm/whatsapp/live`

/**
 * Whether a query shows the chat with `waId` (or any chat, when `waId` is null): the chat lists,
 * the open chat, a lead's conversation, and a campaign's recipient results.
 */
export function showsChat(key: QueryKey, waId: string | null): boolean {
	if (key[0] !== 'crm') return false
	if (key[1] === 'lead') return key[3] === 'whatsapp-thread'
	if (key[1] !== 'whatsapp') return false
	switch (key[2]) {
		case 'chats':
		case 'campaign-chats':
		case 'campaign':
			return true
		case 'chat':
		case 'campaign-chat':
			return waId === null || key[3] === waId
		default:
			return false
	}
}

type LiveOptions = {
	url: string
	token: () => Promise<string | undefined>
	/** A chat changed; null after a reconnect, when anything may have changed meanwhile. */
	onchange: (waId: string | null) => void
}

/** Keeps a socket open, reconnecting with backoff. Returns the function that closes it for good. */
export function connectWhatsAppLive({ url, token, onchange }: LiveOptions): () => void {
	let socket: WebSocket | null = null
	let retry: ReturnType<typeof setTimeout> | undefined
	let attempts = 0
	let stopped = false

	async function open() {
		const jwt = await token()
		if (stopped || !jwt) return
		const ws = new WebSocket(url)
		socket = ws
		ws.onopen = () => ws.send(JSON.stringify({ token: jwt }))
		ws.onmessage = (event) => {
			const message = JSON.parse(event.data)
			if (message.type === 'ready') {
				if (attempts > 0) onchange(null)
				attempts = 0
			} else if (message.type === 'chat.changed') {
				onchange(message.wa_id)
			}
		}
		ws.onclose = (event) => {
			socket = null
			if (stopped || FINAL.has(event.code)) return
			const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempts)
			attempts += 1
			retry = setTimeout(open, delay)
		}
	}

	open()
	return () => {
		stopped = true
		clearTimeout(retry)
		socket?.close()
	}
}
