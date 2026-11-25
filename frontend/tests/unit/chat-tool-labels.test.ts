import { describe, expect, it } from 'vitest'
import { toolDisplayLabel } from '../../src/lib/chat/toolLabels'

describe('assistant progress lines say what actually ran', () => {
	it('distinguishes the CRM workflow from the record reads it makes', () => {
		// One CRM answer runs the workflow and at least one record read. Sharing a label made a
		// single question show "Your CRM records ready" twice, as if the same read repeated.
		for (const state of ['start', 'done'] as const) {
			expect(toolDisplayLabel('retrieve_personal_crm', state)).not.toBe(
				toolDisplayLabel('query_my_crm_records', state)
			)
		}
	})

	it('marks a reused identical read apart from a fresh one', () => {
		expect(toolDisplayLabel('query_my_crm_records', 'done', true)).not.toBe(
			toolDisplayLabel('query_my_crm_records', 'done')
		)
	})
})
