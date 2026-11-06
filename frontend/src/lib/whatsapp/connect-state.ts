import type { AgentConnectionStatus, CanSendMessage } from '$lib/api/whatsapp-connect'

export type ConnectPhase = 'idle' | 'waiting' | 'completing'

export type StepState = 'done' | 'current' | 'upcoming'

/** Connect, choose who to block, turn replies on. The first step not finished is the current one. */
export function stepStates(
	status: AgentConnectionStatus | null
): [StepState, StepState, StepState] {
	if (!status || status.state !== 'connected') return ['current', 'upcoming', 'upcoming']
	if (status.automation_enabled) return ['done', 'done', 'done']
	if (status.contacts.blocked > 0) return ['done', 'done', 'current']
	return ['done', 'current', 'upcoming']
}

export function contactsSyncPending(status: AgentConnectionStatus): boolean {
	return !status.contacts.synced_at
}

export function sendingWarning(
	value: CanSendMessage | null | undefined
): { tone: 'amber' | 'red'; title: string; text: string } | null {
	if (value === 'LIMITED') {
		return {
			tone: 'amber',
			title: 'Meta has limited this number',
			text: 'Some replies may be delayed or not sent. Check the number’s status in Meta’s WhatsApp Manager.'
		}
	}
	if (value === 'BLOCKED') {
		return {
			tone: 'red',
			title: 'Meta has stopped this number from sending',
			text: 'Vitevue cannot reply until it is cleared. Open Meta’s WhatsApp Manager to see why.'
		}
	}
	return null
}

export function healthErrorText(error: unknown): string {
	if (typeof error === 'string' && error.trim()) return error
	if (error && typeof error === 'object') {
		const record = error as Record<string, unknown>
		for (const key of ['error_description', 'message', 'description']) {
			const value = record[key]
			if (typeof value === 'string' && value.trim()) return value
		}
	}
	return 'Meta reported a problem with this number.'
}

export function qualityLabel(rating: string | null): string {
	switch (rating?.toUpperCase()) {
		case 'GREEN':
			return 'Good'
		case 'YELLOW':
			return 'Needs attention'
		case 'RED':
			return 'Poor'
		default:
			return 'Not rated yet'
	}
}

export const WHATSAPP_MANAGER_URL = 'https://business.facebook.com/wa/manage/home'
