import { ApiError } from '$lib/api/client'
import type { ActionStatus, ProposedAction } from './stream'

export interface ActionResult {
	action_id: string
	status: string
	lead_id: number
	href?: string | null
	text?: string | null
}

/** The agent's own version of a proposed email, sent instead of the draft. */
export interface EmailEdits {
	subject: string
	body: string
}

export type CardState = ActionStatus | 'working' | 'error'

interface CardDeps {
	confirm: (actionId: string, edits?: EmailEdits) => Promise<ActionResult>
	cancel: (actionId: string) => Promise<ActionResult>
	/** Runs once after the change is confirmed (refresh the CRM data). */
	onConfirmed: () => void
}

/**
 * Confirm / Cancel for one proposed change. A card acts at most once at a time; a 409 means
 * another tab already resolved it, so the card takes that final state instead of an error.
 */
export function createActionCard(action: ProposedAction, deps: CardDeps) {
	let state = $state<CardState>(action.status)
	let error = $state<string | undefined>()
	let result = $state<ActionResult | undefined>()

	const settle = (e: unknown) => {
		if (e instanceof ApiError && e.status === 410) {
			state = 'expired'
		} else if (e instanceof ApiError && e.status === 409 && /confirmed$/.test(e.message)) {
			state = 'confirmed'
			deps.onConfirmed()
		} else if (
			e instanceof ApiError &&
			e.status === 409 &&
			/(cancelled|expired)$/.test(e.message)
		) {
			state = e.message.endsWith('cancelled') ? 'cancelled' : 'expired'
		} else {
			state = 'error'
			error = e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.'
		}
	}

	const run = async (kind: 'confirm' | 'cancel', edits?: EmailEdits) => {
		if (!action.action_id || !(state === 'pending' || state === 'error')) return
		state = 'working'
		error = undefined
		try {
			const id = action.action_id
			result = await (kind === 'confirm'
				? edits
					? deps.confirm(id, edits)
					: deps.confirm(id)
				: deps.cancel(id))
			state = kind === 'confirm' ? 'confirmed' : 'cancelled'
			if (kind === 'confirm') deps.onConfirmed()
		} catch (e) {
			settle(e)
		}
	}

	return {
		get state() {
			return state
		},
		get error() {
			return error
		},
		get result() {
			return result
		},
		/** Confirm and Cancel are offered only while the action can still run. */
		get canAct() {
			return state === 'pending' || state === 'error'
		},
		confirm: (edits?: EmailEdits) => run('confirm', edits),
		cancel: () => run('cancel')
	}
}
