/** CRM Assistant chat: the SSE events the backend streams, folded into thread messages. */

export type ActionStatus = 'pending' | 'confirmed' | 'cancelled' | 'expired'
export type ActionType = 'status' | 'note' | 'follow_up' | 'assign' | 'share'
export type ShareChannel = 'copy' | 'teammate' | 'whatsapp' | 'email'

/** A change (or share) the assistant proposed; shown as a card the agent confirms. */
export interface ProposedAction {
	/** null for a copy share, which needs no confirmation. */
	action_id: string | null
	action_type: ActionType
	lead_id: number
	summary: string
	before?: Record<string, unknown>
	after?: Record<string, unknown>
	channel?: ShareChannel | null
	/** The lead summary for a copy share. */
	text?: string
	status: ActionStatus
	expires_at?: string
}

export type AssistantEvent =
	| { type: 'text-delta'; content: string }
	| { type: 'tool-status'; tool: string; label: string }
	| { type: 'action-proposed'; action: ProposedAction }
	| { type: 'done' }
	| { type: 'error'; error: string }

export interface ThreadMessage {
	role: 'user' | 'assistant'
	content: string
	actions: ProposedAction[]
	/** What the assistant is doing right now ("Searching leads…"). */
	status?: string
	error?: string
}

/** Apply one event to the last (assistant) message. Returns a new array; the input is unchanged. */
export function applyEvent(messages: ThreadMessage[], event: AssistantEvent): ThreadMessage[] {
	const last = messages.at(-1)
	if (!last || last.role !== 'assistant') return messages
	const next: ThreadMessage = { ...last, actions: [...last.actions] }
	switch (event.type) {
		case 'text-delta':
			next.content += event.content
			break
		case 'tool-status':
			next.status = event.label
			break
		case 'action-proposed':
			next.actions.push(event.action)
			break
		case 'done':
			next.status = undefined
			break
		case 'error':
			next.status = undefined
			next.error = event.error
			break
	}
	return [...messages.slice(0, -1), next]
}

/** Parse one SSE data line; anything that is not a known event is ignored. */
export function parseEvent(data: string): AssistantEvent | null {
	try {
		const parsed = JSON.parse(data)
		return parsed && typeof parsed.type === 'string' ? (parsed as AssistantEvent) : null
	} catch {
		return null
	}
}
