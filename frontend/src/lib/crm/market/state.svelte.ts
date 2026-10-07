/**
 * Market mode state shared across its screens (UI only, 7 Oct): watched zones and items saved
 * to leads show on Market home; the AI chat thread is reused by the floating chat. Kept in
 * memory for the session; nothing is sent to the backend yet.
 */
import { type Answer, answer } from './data'

export interface Saved {
	id: number
	kind: 'Unit report' | 'Shortlist' | 'Project' | 'Plot'
	label: string
	lead: string
	at: string
}

export interface ChatTurn {
	id: number
	q: string
	a: Answer | null
	at: string
}

let seq = 0

function now(): string {
	return new Date().toTimeString().slice(0, 5)
}

class MarketState {
	watched = $state<Record<string, true>>({})
	saved = $state<Saved[]>([])
	shortlist = $state<Record<string, true>>({})
	chat = $state<ChatTurn[]>([])

	toggleWatch(key: string): boolean {
		const on = !this.watched[key]
		const next = { ...this.watched }
		if (on) next[key] = true
		else delete next[key]
		this.watched = next
		return on
	}

	toggleShortlist(key: string): boolean {
		const on = !this.shortlist[key]
		const next = { ...this.shortlist }
		if (on) next[key] = true
		else delete next[key]
		this.shortlist = next
		return on
	}

	save(kind: Saved['kind'], label: string, lead: string): Saved {
		const item = { id: ++seq, kind, label, lead, at: now() }
		this.saved = [...this.saved, item]
		return item
	}

	unsave(id: number) {
		this.saved = this.saved.filter((s) => s.id !== id)
	}

	/** Adds the question now and its answer after a short pause (the typing dots). */
	ask(q: string): ChatTurn {
		const turn: ChatTurn = { id: ++seq, q, a: null, at: now() }
		this.chat = [...this.chat, turn]
		setTimeout(() => {
			this.chat = this.chat.map((t) => (t.id === turn.id ? { ...t, a: answer(q) } : t))
		}, 450)
		return turn
	}

	removeTurn(id: number) {
		this.chat = this.chat.filter((t) => t.id !== id)
	}
}

export const market = new MarketState()

/** Example leads the "Save to a lead" menus offer until Market mode reads the CRM's leads. */
export const EXAMPLE_LEADS = [
	{ id: 'L-101', name: 'Faisal Al Marri', type: 'buyer', area: 'Dubai Hills' },
	{ id: 'L-105', name: 'Mariam K.', type: 'landlord', area: 'Downtown' },
	{ id: 'L-108', name: 'Ahmed Al Hashimi', type: 'landlord', area: 'Dubai Marina' },
	{ id: 'L-111', name: 'Aisha Rahman', type: 'buyer', area: 'JVC' },
	{ id: 'L-102', name: 'Sofia Rossi', type: 'tenant', area: 'JVC' }
]
