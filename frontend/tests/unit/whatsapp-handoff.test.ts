import { describe, expect, it } from 'vitest'

import { handoffDetail, messageText, reasonLabel } from '$lib/whatsapp/handoff'

describe('reasonLabel', () => {
	it('turns known reason codes into a label for the agent', () => {
		expect(reasonLabel('identity_question')).toBe('Asked whether they are talking to a bot')
		expect(reasonLabel('evidence_changed')).toBe(
			'Property facts changed since this draft was written'
		)
		expect(reasonLabel('human_edited')).toBe('You edited this reply')
	})

	it('leaves a reason that is already a sentence alone', () => {
		const sentence = 'Over today’s automatic-reply limit for this contact. Reply yourself.'
		expect(reasonLabel(sentence)).toBe(sentence)
	})

	it('never shows raw snake_case for a code it has not seen', () => {
		expect(reasonLabel('draft_failed')).toBe('Draft failed')
		expect(reasonLabel('not_admitted')).toBe('Not admitted')
		expect(reasonLabel('allowance')).toBe('Allowance')
	})

	it('has nothing to say when there is no reason', () => {
		expect(reasonLabel(null)).toBeNull()
		expect(reasonLabel('')).toBeNull()
	})
})

describe('handoffDetail', () => {
	it('prefers the readable handoff summary over the reason', () => {
		expect(
			handoffDetail({
				handoff_summary: 'Asked whether they’re talking to a bot — reply yourself.',
				reason: 'identity_question',
				topic: null
			})
		).toBe('Asked whether they’re talking to a bot — reply yourself.')
	})

	it('falls back to the reason label, then the topic, then a generic line', () => {
		expect(handoffDetail({ handoff_summary: null, reason: 'identity_question', topic: 'x' })).toBe(
			'Asked whether they are talking to a bot'
		)
		expect(handoffDetail({ handoff_summary: null, reason: null, topic: 'negotiation' })).toBe(
			'Negotiation'
		)
		expect(handoffDetail({ handoff_summary: null, reason: null, topic: null })).toBe(
			'Needs your review'
		)
	})
})

describe('messageText', () => {
	it('shows the customer text when it was kept', () => {
		expect(messageText({ content: 'How many bedrooms?' })).toEqual({
			text: 'How many bedrooms?',
			kept: true
		})
	})

	it('says the text was not saved, and where to read it, when it was deliberately dropped', () => {
		const shown = messageText({ content: null })
		expect(shown.kept).toBe(false)
		expect(shown.text).toBe('Message text not saved. Read it in WhatsApp.')
	})
})
