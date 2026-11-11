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

export interface AutomationFields {
	automation_enabled: boolean
	automation_active: boolean
	automation_paused_reason: string | null
}

export interface AutomationView {
	kind: 'off' | 'on' | 'paused' | 'disconnected'
	label: 'Off' | 'On' | 'Paused' | 'Not connected'
	/** Why replies are not running, in plain words. Null unless they are switched on but not running. */
	note: string | null
	/** What happens next, when it really will happen by itself. Null otherwise. */
	resumeNote: string | null
}

const DISCONNECTED_NOTE =
	'This number is disconnected, so automatic replies are not running. Reconnect it to start them again.'
const RESUME_NOTE =
	'Your switch stays on, so replies start again by themselves when Vitevue resumes them.'

// With replies paused on Vitevue's side, new messages are not answered and not added to the inbox.
const PAUSED_NOTES: Record<string, string> = {
	assistant_disabled:
		'Automatic replies are paused by Vitevue. New messages are not answered or added to the inbox here for now, so keep replying in WhatsApp yourself.',
	intake_disabled:
		'Automatic replies are paused by Vitevue. Vitevue is not reading new WhatsApp messages at the moment, so keep replying in WhatsApp yourself.'
}

/**
 * The agent's own switch is not proof that replies are running: the server can pause them, and a
 * disconnected number cannot send at all. `connection` is the number's connection status; anything
 * other than "connected" means the agent must reconnect, which is not Vitevue's pause.
 */
export function automationView(
	status: AutomationFields,
	connection?: string | null
): AutomationView {
	if (!status.automation_enabled) return { kind: 'off', label: 'Off', note: null, resumeNote: null }
	if (connection && connection !== 'connected') {
		return {
			kind: 'disconnected',
			label: 'Not connected',
			note: DISCONNECTED_NOTE,
			resumeNote: null
		}
	}
	if (status.automation_active) return { kind: 'on', label: 'On', note: null, resumeNote: null }
	const reason = status.automation_paused_reason
	return {
		kind: 'paused',
		label: 'Paused',
		note: (reason && PAUSED_NOTES[reason]) || 'Automatic replies are paused by Vitevue.',
		resumeNote: RESUME_NOTE
	}
}

export interface InboxToggleView {
	kind: AutomationView['kind']
	text: string
	note: string | null
}

/**
 * The inbox's "Automatic replies" switch. The switch itself stays the agent's own setting; this is
 * only what we say beside it. `status` is the connection's status. When the API leaves it out, a
 * switched-on row that is inactive with no pause reason can only be a number that is not connected
 * (the server gives a reason for every pause on a connected number).
 */
export function inboxToggleView(connection: {
	enabled: boolean
	status?: string | null
	automation_active?: boolean
	automation_paused_reason?: string | null
}): InboxToggleView {
	const view = automationView(
		{
			automation_enabled: connection.enabled,
			automation_active: connection.automation_active ?? false,
			automation_paused_reason: connection.automation_paused_reason ?? null
		},
		connection.status ??
			(connection.automation_active === false && connection.automation_paused_reason === null
				? 'disconnected'
				: null)
	)
	if (view.kind === 'off') {
		return {
			kind: 'off',
			text: 'Automatic replies off',
			note: 'Sending is disabled for this number, including approvals.'
		}
	}
	if (view.kind === 'disconnected') {
		return { kind: 'disconnected', text: 'Automatic replies not running', note: view.note }
	}
	return { kind: view.kind, text: `Automatic replies ${view.label.toLowerCase()}`, note: view.note }
}
