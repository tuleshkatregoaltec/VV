import { render } from 'svelte/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type { AuthMeResponse, InboundEnquiryResponse } from '$lib/api/generated/hey-api/types.gen'
import type { LeadType } from '$lib/crm/api/types'
import * as backend from '$lib/crm/api/backend'
import NewLeadPanel from '$lib/crm/components/panels/NewLeadPanel.svelte'

// Qualifying an Inbox contact updates that same enquiry: one PATCH carrying the lead type and its
// brief. The backend then makes it an opportunity with the confirmed intent and criteria, after the
// same visibility and edit checks as any lead edit (tested in the backend suite).

const ME = { id: 'u-1', first_name: 'Sara', last_name: 'Ali' } as AuthMeResponse

function enquiry(overrides: Partial<InboundEnquiryResponse> = {}): InboundEnquiryResponse {
	return {
		id: 41,
		contact: {
			id: 9,
			full_name: 'Hana Unqualified',
			phone: '+971500000001',
			consent_status: 'provided',
			do_not_contact: false
		},
		record_kind: 'unqualified_contact',
		intent: 'unknown',
		status: 'needs_review',
		assigned_user_id: 'u-1',
		source: 'Website',
		enquiry_date: new Date().toISOString(),
		criteria: { notes_seen: 'kept' },
		strict_fields: [],
		observed_data: {},
		inferred_data: {},
		confirmed_data: {},
		qualification: {},
		extraction_confidence: 1,
		review_reasons: [],
		sla_state: 'on_time',
		qualification_complete: false,
		tags: [],
		created_at: new Date().toISOString(),
		updated_at: new Date().toISOString(),
		...overrides
	} as InboundEnquiryResponse
}

afterEach(() => vi.restoreAllMocks())

describe('Inbox offers Qualify lead only for contacts that are not yet a lead', () => {
	it('an unqualified contact can be qualified; typed leads open and recent sellers approve', async () => {
		const list = [
			enquiry({ id: 1 }),
			enquiry({ id: 2, intent: 'buy', record_kind: 'opportunity', status: 'new' }),
			enquiry({ id: 3, source: 'Owner file · recently sold' })
		]
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.startsWith('/api/v1/auth/me')) return ME
			return { enquiries: list, total: list.length, summary: {} }
		})
		const { lists } = await backend.listInbox('all')
		const byId = Object.fromEntries(lists.all.map((x) => [x.id, x]))
		expect(byId['1'].can.qualify).toBe(true)
		expect(byId['1'].lead_id).toBeNull()
		expect(byId['2'].can.qualify).toBe(false)
		expect(byId['2'].lead_id).toBe(2)
		// Recently sold owners keep their own approval flow.
		expect(byId['3'].can.qualify).toBe(false)
		expect(byId['3'].can.approve).toBe(true)
	})

	it('passes saved structured criteria into the qualification form', async () => {
		const saved = enquiry({
			criteria: {
				notes_seen: 'keep separate',
				locations: ['JVC'],
				property_type: 'Villa',
				bedrooms_min: 3,
				bedrooms_max: 3,
				budget_max_aed: 4_550_000
			}
		})
		vi.spyOn(client, 'get').mockImplementation(async (url: string) =>
			url.startsWith('/api/v1/auth/me') ? ME : { enquiries: [saved], total: 1, summary: {} }
		)
		const { lists } = await backend.listInbox('all')
		expect(lists.all[0].qualify_prefill).toEqual({
			area: 'JVC',
			fields: { wants: 'Villa', bedrooms: '3', budget_aed: 4_550_000 }
		})
	})
})

describe('qualifying saves the type and brief on the same enquiry', () => {
	const cases: [LeadType, string, Record<string, unknown>, Record<string, unknown>][] = [
		['buyer', 'buy', { budget_aed: 1_500_000 }, { budget_max_aed: 1_500_000, locations: ['JVC'] }],
		['tenant', 'rent', { budget_aed: 120_000 }, { budget_max_aed: 120_000, locations: ['JVC'] }],
		[
			'seller',
			'sell',
			{ building: 'Marina Gate', unit_number: '1204' },
			{ building: 'Marina Gate', unit_number: '1204' }
		],
		[
			'landlord',
			'let',
			{ building: 'Bloom Towers', unit_number: '305' },
			{ building: 'Bloom Towers', unit_number: '305' }
		]
	]

	it.each(cases)('%s → intent %s', async (type, intent, fields, saved) => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) =>
			url.startsWith('/api/v1/auth/me') ? ME : enquiry()
		)
		const patch = vi
			.spyOn(client, 'patch')
			.mockImplementation(async (_url: string, body: unknown) =>
				enquiry({ ...(body as object), record_kind: 'opportunity' })
			)
		const area = type === 'buyer' || type === 'tenant' ? 'JVC' : ''
		const result = await backend.qualifyLead(41, { lead_type: type, area, fields })

		expect(patch).toHaveBeenCalledTimes(1)
		const [url, body] = patch.mock.calls[0] as [string, Record<string, unknown>]
		// The existing enquiry, never a new one; nothing about who holds it or its stage.
		expect(url).toBe('/api/v1/crm/inbound/enquiries/41')
		expect(Object.keys(body).sort()).toEqual(['criteria', 'intent'])
		expect(body.intent).toBe(intent)
		// The brief is added to what the contact already had.
		expect(body.criteria).toEqual({ notes_seen: 'kept', ...saved })
		expect(result.data.id).toBe(41)
		expect(result.data.lead_type).toBe(type)
	})
})

describe('the qualify form', () => {
	it('asks only for the lead type and brief, not the contact the enquiry already has', () => {
		const html = render(NewLeadPanel, {
			props: {
				qualify: {
					id: 41,
					name: 'Hana Unqualified',
					prefill: {
						area: 'JVC',
						fields: { wants: 'Villa', bedrooms: '3', budget_aed: 4_550_000 }
					}
				}
			}
		}).body
		expect(html).toContain('Qualify Hana Unqualified')
		expect(html).toContain('Qualify lead')
		for (const label of ['Buyer', 'Seller', 'Tenant', 'Landlord']) expect(html).toContain(label)
		expect(html).toContain('id="nl-budget_aed"')
		expect(html).toContain('id="nl-area"')
		expect(html).toContain('value="JVC"')
		expect(html).toContain('value="4,550,000"')
		for (const field of ['nl-name', 'nl-phone', 'nl-source']) expect(html).not.toContain(`id="${field}"`)
	})

	it('the New Lead form is unchanged', () => {
		const html = render(NewLeadPanel, { props: {} }).body
		for (const field of ['nl-name', 'nl-phone', 'nl-source']) expect(html).toContain(`id="${field}"`)
		expect(html).toContain('Create lead')
	})
})
