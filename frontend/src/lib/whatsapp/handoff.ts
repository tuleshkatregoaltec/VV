import type { CustomerMessageResponse } from '$lib/api/generated/hey-api/types.gen'

const REASONS: Record<string, string> = {
	identity_question: 'Asked whether they are talking to a bot',
	evidence_changed: 'Property facts changed since this draft was written',
	human_edited: 'You edited this reply',
	human_cancelled: 'You cancelled this draft',
	agent_replied: 'You replied in WhatsApp'
}

const CODE = /^[a-z][a-z0-9]*(_[a-z0-9]+)*$/

/** "draft_failed" -> "Draft failed". Backend reasons are sometimes codes, sometimes sentences. */
function sentenceCase(code: string): string {
	const text = code.replaceAll('_', ' ')
	return text.charAt(0).toUpperCase() + text.slice(1)
}

export function reasonLabel(reason: string | null | undefined): string | null {
	if (!reason) return null
	if (REASONS[reason]) return REASONS[reason]
	return CODE.test(reason) ? sentenceCase(reason) : reason
}

/** The one line telling the agent why this needs them. */
export function handoffDetail(
	item: Pick<CustomerMessageResponse, 'handoff_summary' | 'reason' | 'topic'>
): string {
	return (
		item.handoff_summary ||
		reasonLabel(item.reason) ||
		(item.topic ? sentenceCase(item.topic) : null) ||
		'Needs your review'
	)
}

/** Text is null when it was deliberately not kept, never because it is still loading. */
export function messageText(item: Pick<CustomerMessageResponse, 'content'>): {
	text: string
	kept: boolean
} {
	return item.content
		? { text: item.content, kept: true }
		: { text: 'Message text not saved. Read it in WhatsApp.', kept: false }
}
