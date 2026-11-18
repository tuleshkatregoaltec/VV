import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type {
	AuthMeResponse,
	CrmLead,
	CrmOwnerProfile,
	CrmRenewalLeadsResponse,
	InboundEnquiryResponse
} from '$lib/api/generated/hey-api/types.gen'
import * as backend from '$lib/crm/api/backend'

const ME: AuthMeResponse = {
	id: 'u-1',
	email: 'sara@agency.ae',
	first_name: 'Sara',
	last_name: 'Ali',
	organization_id: 'org-1',
	organization_name: 'Agency',
	role: 'member',
	is_owner: false,
	subscription_status: 'active'
} as AuthMeResponse

function enquiry(overrides: Partial<InboundEnquiryResponse> = {}): InboundEnquiryResponse {
	return {
		id: 7,
		contact: {
			id: 1,
			full_name: 'Omar Khan',
			phone: '+971500000000',
			consent_status: 'provided',
			do_not_contact: false,
			registry_profiles: []
		},
		record_kind: 'opportunity',
		intent: 'buy',
		status: 'new',
		assigned_user_id: 'u-1',
		source: 'Bayut',
		enquiry_date: new Date().toISOString(),
		criteria: {
			bedrooms_min: 2,
			property_type: 'Apartment',
			locations: ['JVC'],
			budget_max_aed: 1_500_000
		},
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

/** Route client.get by path so each test states only the backend data it cares about. */
function serve(routes: Record<string, unknown>) {
	return vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		const path = url.split('?')[0]
		if (path === '/api/v1/auth/me') return ME
		if (path in routes) return routes[path]
		throw new Error(`unexpected GET ${url}`)
	})
}

afterEach(() => vi.restoreAllMocks())

describe('CRM leads from /api/v1/crm/inbound', () => {
	it.each([
		['not_checked', false, 'Ownership not checked'],
		['stored', true, 'Ownership on file']
	] as const)('keeps real leads and labels %s ownership accurately', async (verification, matched, label) => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({
						ownership_enrichment: {
							verification,
							matched,
							reasons: [label]
						}
					})
				],
				total: 1,
				summary: {}
			}
		})
		const res = await backend.listLeads({})
		expect(res.items).toHaveLength(1)
		expect(res.items[0].name).toBe('Omar Khan')
		expect(res.items[0].known).toBe(label)
	})

	it('asks only for leads, so Inbox contacts cannot crowd them out of the page', async () => {
		const get = serve({ '/api/v1/crm/inbound/enquiries': { enquiries: [], total: 0, summary: {} } })
		await backend.listLeads({})
		const url = get.mock.calls.map(([u]) => String(u)).find((u) => u.includes('/inbound/enquiries'))
		expect(url).toContain('leads_only=true')
	})

	it('keeps unqualified contacts (intent unknown) out of Leads: they are Inbox work, not a typed lead', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({ id: 1 }),
					enquiry({ id: 2, intent: 'unknown', record_kind: 'unqualified_contact' })
				],
				total: 2,
				summary: {}
			}
		})
		const res = await backend.listLeads({})
		expect(res.items.map((l) => l.id)).toEqual([1])
		expect(res.counts.all).toBe(1)
	})

	it.each([
		{ building: 'null', unit_number: 'NULL' },
		{ building: 'NULL', unit_number: '#NULL' },
		{ building: 'undefined', unit_number: 'NaN' },
		{ unit: 'null #NULL' }
	])('shows a missing unit as not stated, never as the text "null" (%o)', async (criteria) => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({ id: 5, intent: 'sell', criteria: { locations: ['JVC'], ...criteria } })
				],
				total: 1,
				summary: {}
			}
		})
		const [row] = (await backend.listLeads({})).items
		expect(row.summary.line).toBe('Unit not stated')
		expect(row.fields.unit).toBeUndefined()
		expect(JSON.stringify(row)).not.toMatch(/null #|#null|"null"|undefined/i)
	})

	it('keeps a real building and unit number and drops only the missing half', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({
						id: 5,
						intent: 'sell',
						criteria: { building: 'FIVE LUXE', unit_number: 'NULL' }
					}),
					enquiry({
						id: 6,
						intent: 'sell',
						criteria: { building: 'Null Tower', unit_number: '4901' }
					})
				],
				total: 2,
				summary: {}
			}
		})
		const lines = (await backend.listLeads({})).items.map((l) => l.summary.line)
		expect(lines).toEqual(['FIVE LUXE', 'Null Tower #4901'])
	})

	it('maps backend statuses onto the stage bar of each lead type', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({ id: 1, intent: 'sell', status: 'signed' }),
					enquiry({ id: 2, intent: 'buy', status: 'attempted' }),
					enquiry({ id: 3, intent: 'rent', status: 'disqualified' })
				],
				total: 3,
				summary: {}
			}
		})
		const res = await backend.listLeads({})
		// A signed seller instruction is "Listed"; an attempt counts as Contacted.
		expect(res.items.map((l) => [l.id, l.stage])).toEqual([
			[1, 'listed'],
			[2, 'contacted']
		])
		// Disqualified leads only show under Lost.
		expect(res.counts.lost).toBe(1)
		expect((await backend.listLeads({ lost: true })).items.map((l) => l.id)).toEqual([3])
	})

	it("gives the board its lost leads, so a lead moved to Lost shows in the board's Lost column", async () => {
		// 11 Nov: a lead moved to Lost vanished from the board, whose Lost column could never fill.
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [
					enquiry({ id: 1, intent: 'buy', status: 'contacted' }),
					enquiry({ id: 2, intent: 'buy', status: 'closed_lost' })
				],
				total: 2,
				summary: {}
			}
		})
		const res = await backend.listLeads({ include_lost: true })
		expect(res.items.map((l) => [l.id, l.stage])).toEqual([
			[1, 'contacted'],
			[2, 'lost']
		])
		// The tab counts are unchanged: All still leaves lost leads out.
		expect(res.counts.all).toBe(1)
		expect(res.counts.lost).toBe(1)
	})

	it('reads criteria into the buyer brief the Leads table shows', async () => {
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry() })
		const lead = await backend.getLead(7)
		// Wants is the property type the matcher filters on; the table line keeps the full brief.
		expect(lead.fields.wants).toBe('Apartment')
		expect(lead.summary.line).toBe('2 bed Apartment in JVC')
		expect(lead.fields.budget_aed).toBe(1_500_000)
		expect(lead.area).toBe('JVC')
		expect(lead.agent).toBe('Sara Ali')
	})

	it('does not offer Undo or a linked deal on a backend lead: neither is recorded yet', async () => {
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry() })
		const lead = await backend.getLead(7)
		expect(lead.can_undo).toBe(false)
		expect(lead.deal).toBeNull()
	})

	it('saves the Offer stage, with the amount and unit as a note on the lead', async () => {
		// The backend stores an "offer" status (11 Nov): Move to Offer used to fail with a
		// misleading "server had a problem" before anything was sent.
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry({ status: 'viewing' }) })
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(enquiry({ status: 'offer' }))
		const post = vi.spyOn(client, 'post').mockResolvedValue(enquiry({ status: 'offer' }))
		const r = await backend.moveLeadStage(7, {
			stage: 'offer',
			offer: { amount_aed: 225_000, listing_id: 'L-9', unit: 'Metro | Lake View' }
		})
		expect(patch.mock.calls[0][1]).toMatchObject({ status: 'offer' })
		expect(post.mock.calls[0][1]).toEqual({ body: 'Offer AED 225,000 · Metro | Lake View' })
		expect(r.data.stage).toBe('offer')
	})

	it('saves a buyer at Won with the agreed price, unit and target date as a note', async () => {
		// Deals have no backend yet (11 Nov): Offer → Won used to try to open a deal and fail with
		// "Creating a deal isn't available". The lead's own status records the win instead.
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry({ status: 'offer' }) })
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(enquiry({ status: 'won' }))
		const post = vi.spyOn(client, 'post').mockResolvedValue(enquiry({ status: 'won' }))
		const r = await backend.moveLeadStage(7, {
			stage: 'won',
			won: { value_aed: 225_000, unit: 'Metro | Lake View', due_date: '2026-12-02' }
		})
		expect(patch.mock.calls[0][1]).toMatchObject({ status: 'won' })
		expect(post.mock.calls[0][1]).toEqual({
			body: 'Won AED 225,000 · Metro | Lake View · target 2026-12-02'
		})
		expect(r.data.stage).toBe('won')
	})

	it("notes who a seller's offer came from", async () => {
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry({ intent: 'sell', status: 'signed' }) })
		vi.spyOn(client, 'patch').mockResolvedValue(enquiry({ intent: 'sell', status: 'offer' }))
		const post = vi
			.spyOn(client, 'post')
			.mockResolvedValue(enquiry({ intent: 'sell', status: 'offer' }))
		const r = await backend.moveLeadStage(7, {
			stage: 'offer',
			offer: { amount_aed: 2_100_000, from: 'Buyer agent' }
		})
		expect(post.mock.calls[0][1]).toEqual({ body: 'Offer AED 2,100,000 · from Buyer agent' })
		expect(r.data.stage).toBe('offer')
	})

	it('gives the Edit form the saved areas, so the area matching uses can be seen and changed', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries/7': enquiry({
				criteria: { ...enquiry().criteria, locations: ['Dubai Marina', 'JBR'] }
			})
		})
		expect((await backend.getLead(7)).fields.areas).toBe('Dubai Marina, JBR')
	})

	it('saves Bedrooms as the bedroom range matching reads', async () => {
		// Matching filters listings on bedrooms_min/max; the forms had no way to set them.
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry() })
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(enquiry())
		const sent = async (bedrooms: string) => {
			patch.mockClear()
			await backend.patchLead(7, { fields: { bedrooms } })
			return (patch.mock.calls[0][1] as { criteria: Record<string, unknown> }).criteria
		}
		expect(await sent('2')).toMatchObject({ bedrooms_min: 2, bedrooms_max: 2 })
		expect(await sent('Studio')).toMatchObject({ bedrooms_min: 0, bedrooms_max: 0 })
		const many = await sent('7+')
		expect(many.bedrooms_min).toBe(7)
		expect(many).not.toHaveProperty('bedrooms_max')
	})

	it('shows the saved bedroom range as the Bedrooms option', async () => {
		for (const [range, shown] of [
			[{ bedrooms_min: 2, bedrooms_max: 2 }, '2'],
			[{ bedrooms_min: 0, bedrooms_max: 0 }, 'Studio'],
			[{ bedrooms_min: 7 }, '7+']
		] as const) {
			const { bedrooms_min: _m, bedrooms_max: _x, ...rest } = enquiry().criteria
			serve({ '/api/v1/crm/inbound/enquiries/7': enquiry({ criteria: { ...rest, ...range } }) })
			expect((await backend.getLead(7)).fields.bedrooms).toBe(shown)
		}
	})

	it('saves the Wants choice as the property type matching filters on', async () => {
		// Wants used to be free text under its own key, which matching never read: "Villa" typed
		// there still matched apartments. The dropdown writes property_type and drops the old text.
		serve({
			'/api/v1/crm/inbound/enquiries/7': enquiry({
				criteria: { ...enquiry().criteria, wants: '2 bed apartment' }
			})
		})
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(enquiry())
		await backend.patchLead(7, { fields: { wants: 'Villa' } })
		const sent = (patch.mock.calls[0][1] as { criteria: Record<string, unknown> }).criteria
		expect(sent.property_type).toBe('Villa')
		expect(sent).not.toHaveProperty('wants')
	})

	it('shows older type names from imports as the matching dropdown option', async () => {
		for (const [stored, shown] of [
			['Flat', 'Apartment'],
			['Residential Flats', 'Apartment'],
			['Unit', 'Apartment'],
			['Villas', 'Villa'],
			['villa', 'Villa'],
			['Office Space', 'Office Space']
		]) {
			serve({
				'/api/v1/crm/inbound/enquiries/7': enquiry({
					criteria: { ...enquiry().criteria, property_type: stored }
				})
			})
			expect((await backend.getLead(7)).fields.wants).toBe(shown)
		}
	})

	it('writes edited fields back under the criteria keys the backend matcher reads', async () => {
		serve({ '/api/v1/crm/inbound/enquiries/7': enquiry() })
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(enquiry())
		await backend.patchLead(7, { fields: { budget_aed: 2_000_000, areas: 'JVC, Dubai Marina' } })
		expect(patch).toHaveBeenCalledWith('/api/v1/crm/inbound/enquiries/7', {
			criteria: expect.objectContaining({
				budget_max_aed: 2_000_000,
				locations: ['JVC', 'Dubai Marina']
			})
		})
	})
})

describe('New Lead form saves every field of every lead type (POST /api/v1/crm/inbound/enquiries)', () => {
	// What the agent typed must reach the backend under the keys it stores and matches on, and
	// come back unchanged when the lead is opened; a lost field is a lost part of the brief.
	const cases = [
		{
			type: 'buyer',
			intent: 'buy',
			fields: {
				wants: 'Villa',
				bedrooms: '4',
				budget_aed: 1_500_000,
				finance: 'Mortgage',
				purpose: 'Invest',
				timeline: '3 months'
			},
			criteria: {
				property_type: 'Villa',
				bedrooms_min: 4,
				bedrooms_max: 4,
				budget_max_aed: 1_500_000,
				financing: 'Mortgage',
				purpose: 'Invest',
				timeline: '3 months'
			}
		},
		{
			type: 'seller',
			intent: 'sell',
			fields: {
				building: 'Bloom Towers A',
				unit_number: '1204',
				target_price_aed: 2_100_000,
				occupancy: 'Vacant',
				mortgage: 'None',
				timeline: 'This month'
			},
			criteria: {
				building: 'Bloom Towers A',
				unit_number: '1204',
				expected_price_aed: 2_100_000,
				occupancy: 'Vacant',
				mortgage: 'None',
				timeline: 'This month'
			}
		},
		{
			type: 'tenant',
			intent: 'rent',
			fields: { wants: 'Apartment', budget_aed: 65_000, cheques: '4', move_in: 'December' },
			criteria: {
				property_type: 'Apartment',
				budget_max_aed: 65_000,
				cheques: '4',
				move_in: 'December'
			}
		},
		{
			type: 'landlord',
			intent: 'let',
			fields: {
				building: 'Marina Heights',
				unit_number: '3301',
				expected_rent_aed: 120_000,
				available: 'January',
				furnishing: 'Furnished'
			},
			criteria: {
				building: 'Marina Heights',
				unit_number: '3301',
				expected_rent_aed: 120_000,
				available: 'January',
				furnishing: 'Furnished'
			}
		}
	] as const

	for (const c of cases) {
		it(`${c.type}: sends every field and reads it back`, async () => {
			serve({})
			const post = vi
				.spyOn(client, 'post')
				.mockImplementation(async (_url: string, body: unknown) => {
					// The backend stores criteria as given (a JSON column), so echo it back.
					const b = body as {
						intent: string
						full_name: string
						criteria: Record<string, unknown>
					}
					return enquiry({
						intent: b.intent as InboundEnquiryResponse['intent'],
						criteria: b.criteria,
						contact: { ...enquiry().contact, full_name: b.full_name }
					})
				})

			const res = await backend.createLead({
				name: 'Test Lead',
				phone: '050 123 4567',
				source: 'inbound',
				source_detail: 'Property Finder',
				lead_type: c.type,
				area: 'JVC, Dubai Marina',
				fields: { ...c.fields }
			})

			expect(post).toHaveBeenCalledWith('/api/v1/crm/inbound/enquiries', {
				intent: c.intent,
				record_kind: 'opportunity',
				full_name: 'Test Lead',
				phone: '050 123 4567',
				source: 'Property Finder',
				criteria: { ...c.criteria, locations: ['JVC', 'Dubai Marina'] }
			})
			expect(res.data.name).toBe('Test Lead')
			expect(res.data.fields).toMatchObject({ ...c.fields, areas: 'JVC, Dubai Marina' })
			// The Leads table headline shows the first area; the full list stays in the brief.
			expect(res.data.area).toBe('JVC')
		})
	}
})

describe('CRM owners from /api/v1/crm/owner-registry', () => {
	const owner = (key: string, units: number, leaseInDays: number | null): CrmOwnerProfile => {
		const end =
			leaseInDays === null
				? null
				: new Date(Date.now() + leaseInDays * 864e5).toISOString().slice(0, 10)
		return {
			owner_key: key,
			contact_name: `Owner ${key}`,
			highest_ownership_status: 'verified_current_owner',
			highest_confidence_score: 90,
			property_count: units,
			rental_linked_count: 0,
			contact_ready_count: units,
			annual_rent_aed: 0,
			next_lease_end: end,
			properties: Array.from({ length: units }, (_, i) => ({
				property_key: `${key}-${i}`,
				area_name: 'JVC',
				project_name: 'Bloom',
				building_name: 'Bloom Towers',
				unit_number: String(100 + i),
				property_type: 'Apartment',
				ownership_status: 'verified_current_owner',
				confidence_score: 90,
				match_reason: ''
			}))
		} as CrmOwnerProfile
	}

	it('counts the tabs the agent filters by (3+ units, a lease ending within 90 days) on the backend, for the whole file', async () => {
		const page = {
			owners: [owner('a', 3, 30), owner('b', 1, 200), owner('c', 1, null)],
			limit: 500,
			offset: 0,
			summary: {}
		}
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.startsWith('/api/v1/crm/owner-workspaces')) return [] as never
			if (!url.startsWith('/api/v1/crm/owner-registry')) throw new Error(`unexpected GET ${url}`)
			// The backend applies the tab filters: one owner has 3+ units, one a lease within 90 days.
			const total = url.includes('min_properties=3') || url.includes('next_event_days=90') ? 1 : 3
			return { ...page, total } as never
		})
		const res = await backend.listOwners({ tab: 'all' })
		expect(res.page).toMatchObject({ total: 3, loaded: 3 })
		expect(res.items[0].units).toEqual([
			'Bloom Towers #100',
			'Bloom Towers #101',
			'Bloom Towers #102'
		])
	})

	it('keeps the DLD 02-2026 gate on: no owner has a prior deal on record yet', async () => {
		serve({
			'/api/v1/crm/owners/a': owner('a', 1, 30),
			'/api/v1/crm/owner-workspaces': [],
			'/api/v1/crm/contact-imports': []
		})
		const o = await backend.getOwner('a')
		expect(o.prior_deal).toBe(false)
		expect(o.create_lead).toBeNull()
	})
})

describe('CRM market listings from /api/v1/listings', () => {
	const card = (id: string, price: number, estimate: number | null) => ({
		listing_id: id,
		listing_mode: 'sale',
		title: 'Listing',
		tower_name: 'Marina Gate 1',
		bedrooms: '2',
		area_name: 'Dubai Marina',
		price_value: price,
		market_estimate_aed: estimate,
		listing_age_days: 12
	})

	it('computes the discount from price vs matching sales and drops listings with no estimate', async () => {
		serve({
			'/api/v1/listings': {
				listings: [
					card('a', 900_000, 1_000_000),
					card('b', 1_100_000, 1_000_000),
					card('c', 1, null)
				]
			}
		})
		const list = await backend.listMarket()
		// Sale and rent are both fetched from the same stub, so each listing appears twice.
		const a = list.find((m) => m.id === 'a')
		const b = list.find((m) => m.id === 'b')
		expect(a).toMatchObject({
			discount_pct: 10,
			discount_chip: { tone: 'green', label: '10% under' }
		})
		expect(b).toMatchObject({
			discount_pct: -10,
			discount_chip: { tone: 'amber', label: '10% over' }
		})
		expect(list.some((m) => m.id === 'c')).toBe(false)
		expect(list[0].id).toBe('a')
	})
	it('does not turn a suppressed stale or low-confidence raw valuation into an under-market badge', async () => {
		serve({
			'/api/v1/listings': {
				listings: [
					{
						...card('stale', 900_000, null),
						valuation_method: 'dld_sales',
						estimated_value_aed: 1_000_000,
						market_position: 'insufficient_data',
						value_gap_pct: null,
						valuation_confidence: 'high',
						valued_at: '2025-01-01'
					},
					{
						...card('low-confidence', 900_000, null),
						valuation_method: 'dld_sales',
						estimated_value_aed: 1_000_000,
						market_position: 'insufficient_data',
						value_gap_pct: null,
						valuation_confidence: 'low'
					}
				]
			}
		})
		expect(await backend.listMarket()).toEqual([])
	})
})

function lease(overrides: Partial<CrmLead> = {}): CrmLead {
	return {
		lead_id: 'lease-1',
		unit_candidate_key: 'unit-1',
		building_name: 'Bloom Towers',
		project_name: '',
		area_name: 'Jumeirah Village Circle',
		property_type: 'Apartment',
		property_subtype: 'Apartment',
		bedrooms: '1 Bed',
		size_sqft: 750,
		annual_rent_aed: 85_000,
		unit_number: null,
		lease_start: '2025-12-08',
		lease_end: '2026-12-07',
		days_to_expiry: 60,
		status: 'expiring_90',
		priority: 'medium',
		score: 66,
		contract_state: 'New',
		match_confidence: 'low',
		lead_reason: 'Lease expires in 60 days; begin a renewal-status conversation.',
		recommended_action: 'Resolve the exact unit, then contact the owner.',
		sale_conversation: false,
		...overrides
	} as CrmLead
}

function renewalLeads(items: CrmRenewalLeadsResponse['items']): CrmRenewalLeadsResponse {
	return {
		items,
		total: items.length,
		limit: 500,
		offset: 0,
		entered_today: 1,
		preferences: { areas: ['Jumeirah Village Circle'], forward_days: 60, lookback_days: 30 },
		as_of: '2026-10-08'
	}
}

const NO_ENQUIRIES = { enquiries: [], total: 0, summary: {} }

/** A stored Vitevue lease lead as the backend returns it once an agent has opened the unit. */
function openedLease(id: number): InboundEnquiryResponse {
	return enquiry({
		id,
		intent: 'unknown',
		record_kind: 'unqualified_contact',
		source: 'Vitevue lease lead',
		contact: { ...enquiry().contact, full_name: '', phone: null },
		criteria: {
			building: 'Bloom Towers',
			unit_number: '216',
			locations: ['Jumeirah Village Circle']
		},
		observed_data: {
			vitevue_lease: {
				lease_id: 'lease-1',
				lease_start: '2025-12-08',
				lease_end: '2026-12-07',
				annual_rent_aed: 85_000,
				vacant: false
			}
		}
	})
}

describe('Vitevue lease leads in Leads (/api/v1/crm/renewal-leads)', () => {
	it('lists unopened units as undecided Vitevue leads with a blank owner, never a guessed one', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': NO_ENQUIRIES,
			'/api/v1/crm/renewal-leads': renewalLeads([
				{ lead: lease({ unit_number: '216' }), owner: null }
			])
		})
		const { crm } = await import('$lib/crm/api')
		const [row] = (await crm.leads.list({ vitevue: true })).items
		expect(row).toMatchObject({
			id: 0,
			lead_type: 'owner',
			source: 'vitevue',
			name: 'Bloom Towers · unit 216',
			known: 'Owner not identified yet'
		})
	})

	it('loads upcoming renewals first, one server page at a time, soonest end on top', async () => {
		const get = serve({
			'/api/v1/crm/inbound/enquiries': NO_ENQUIRIES,
			'/api/v1/crm/renewal-leads': {
				...renewalLeads([
					{ lead: lease({ lead_id: 'ends-3', days_to_expiry: 3 }), owner: null },
					{ lead: lease({ lead_id: 'ends-60', days_to_expiry: 60 }), owner: null }
				]),
				kind: 'upcoming',
				total: 3657,
				limit: 100,
				counts: { all: 4452, upcoming: 3657, expired: 795, vacant: 300 }
			}
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.leads.list({ vitevue: true })
		const url = String(get.mock.calls.find(([u]) => String(u).includes('renewal-leads'))?.[0])
		expect(url).toContain('kind=upcoming')
		expect(url).toContain('limit=100')
		expect(url).toContain('offset=0')
		expect(res.items.map((r) => r.lease?.id)).toEqual(['ends-3', 'ends-60'])
		expect(res.lease_page).toEqual({
			window: 'upcoming',
			offset: 0,
			limit: 100,
			total: 3657,
			counts: { upcoming: 3657, expired: 795, vacant: 300 }
		})
		// The pager covers the lease leads, so loaded rows are not "limited".
		expect(res.limited).toBe(false)
	})

	it('lists expired leases separately, vacant units first, and pages through them', async () => {
		const get = serve({
			'/api/v1/crm/inbound/enquiries': NO_ENQUIRIES,
			'/api/v1/crm/renewal-leads': {
				...renewalLeads([
					{
						lead: lease({
							lead_id: 'ended',
							days_to_expiry: -2,
							lease_evidence_state: 'unit_unresolved'
						}),
						owner: null
					},
					{
						lead: lease({
							lead_id: 'vacant',
							days_to_expiry: -5,
							lease_evidence_state: 'unlet_signal'
						}),
						owner: null
					}
				]),
				kind: 'expired',
				total: 795,
				offset: 100,
				limit: 100,
				counts: { all: 4452, upcoming: 3657, expired: 795, vacant: 300 }
			}
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.leads.list({ vitevue: true, lease_window: 'expired', lease_offset: 100 })
		const url = String(get.mock.calls.find(([u]) => String(u).includes('renewal-leads'))?.[0])
		expect(url).toContain('kind=expired')
		expect(url).toContain('offset=100')
		expect(res.items.map((r) => r.lease?.id)).toEqual(['vacant', 'ended'])
		expect(res.lease_page?.total).toBe(795)
	})

	it('never shows the 1970 placeholder as a purchase date', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': NO_ENQUIRIES,
			'/api/v1/crm/renewal-leads': renewalLeads([
				{ lead: lease({ last_purchase_date: '1970-01-01' }), owner: null }
			])
		})
		const { crm } = await import('$lib/crm/api')
		const [row] = (await crm.leads.list({ vitevue: true })).items
		expect(row.lease?.last_purchase).toBeNull()
	})

	it('shows a unit once: an opened unit is its stored lead, not a second row', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': { enquiries: [openedLease(7)], total: 1, summary: {} },
			'/api/v1/crm/renewal-leads': renewalLeads([
				{ lead: lease({ unit_number: '216' }), owner: null, lead_record_id: 7 }
			])
		})
		const { crm } = await import('$lib/crm/api')
		const { items } = await crm.leads.list({ vitevue: true })
		expect(items).toHaveLength(1)
		expect(items[0]).toMatchObject({ id: 7, lead_type: 'owner', name: 'Bloom Towers · unit 216' })
	})

	it('keeps undecided Vitevue leads out of Home, counts and Matches', async () => {
		const get = serve({
			'/api/v1/crm/inbound/enquiries': { enquiries: [openedLease(7)], total: 1, summary: {} }
		})
		const { crm } = await import('$lib/crm/api')
		expect((await crm.leads.list({})).items).toEqual([])
		expect(get.mock.calls.some(([u]) => String(u).includes('renewal-leads'))).toBe(false)
	})

	it("still lists the agency's own leads when the lease data cannot load, and says so", async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.startsWith('/api/v1/auth/me')) return ME
			if (url.startsWith('/api/v1/crm/inbound/enquiries'))
				return { enquiries: [enquiry({ id: 1 })], total: 1, summary: {} }
			throw new Error('ClickHouse timed out')
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.leads.list({ vitevue: true })
		expect(res.items.map((r) => r.id)).toEqual([1])
		expect(res.vitevue_unavailable).toBe(true)
	})

	it('opens a unit as the shared lead for it', async () => {
		serve({})
		const post = vi.spyOn(client, 'post').mockResolvedValue(openedLease(7))
		const { crm } = await import('$lib/crm/api')
		const res = await crm.leads.openVitevue('lease-1')
		expect(post).toHaveBeenCalledWith('/api/v1/crm/renewal-leads/lease-1/lead')
		expect(res.data.id).toBe(7)
	})

	it("saves the owner the agent finds as the lead's contact name, phone and email", async () => {
		serve({ '/api/v1/crm/inbound/enquiries/7': openedLease(7) })
		const patch = vi.spyOn(client, 'patch').mockResolvedValue(openedLease(7))
		const { crm } = await import('$lib/crm/api')
		await crm.leads.patch(7, { name: 'Huda Saeed', phone: '0501234567', email: 'huda@example.com' })
		expect(patch.mock.calls[0][1]).toMatchObject({
			full_name: 'Huda Saeed',
			phone: '0501234567',
			email: 'huda@example.com'
		})
	})

	it('reports the saved areas and windows in the Leads feed strip', async () => {
		serve({
			'/api/v1/crm/renewal-leads': {
				...renewalLeads([{ lead: lease(), owner: null }]),
				counts: { all: 4452, upcoming: 3657, expired: 795, vacant: 300 }
			}
		})
		const { crm } = await import('$lib/crm/api')
		expect(await crm.feed.summary()).toEqual({
			areas: ['Jumeirah Village Circle'],
			forward_days: 60,
			lookback_days: 30,
			// Every unit in the window, not the loaded page.
			window_total: 4452,
			upcoming: 3657,
			expired: 795,
			on_file: 0,
			loaded: 1,
			entered_today: 1
		})
	})

	it('shares one lease request between the Leads list and its feed strip', async () => {
		const get = serve({
			'/api/v1/crm/inbound/enquiries': NO_ENQUIRIES,
			'/api/v1/crm/renewal-leads': renewalLeads([{ lead: lease(), owner: null }])
		})
		const { crm } = await import('$lib/crm/api')
		await Promise.all([crm.leads.list({ vitevue: true }), crm.feed.summary()])
		const calls = get.mock.calls.filter(([u]) => String(u).startsWith('/api/v1/crm/renewal-leads'))
		expect(calls).toHaveLength(1)
	})
})

describe('Inbox from /api/v1/crm/inbound/enquiries', () => {
	/** Answer each Inbox query (workspace=inbox, workspace=unqualified, status=disqualified). */
	function serveInbox(lists: {
		inbox?: InboundEnquiryResponse[]
		unqualified?: InboundEnquiryResponse[]
		disqualified?: InboundEnquiryResponse[]
	}) {
		return vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.startsWith('/api/v1/auth/me')) return ME
			const pick = url.includes('workspace=inbox')
				? lists.inbox
				: url.includes('workspace=unqualified')
					? lists.unqualified
					: url.includes('status=disqualified')
						? lists.disqualified
						: undefined
			if (pick === undefined) throw new Error(`unexpected GET ${url}`)
			return { enquiries: pick, total: pick.length, summary: {} }
		})
	}

	it('holds enquiries waiting for a first reply and unqualified contacts, not Vitevue lease leads', async () => {
		serveInbox({
			inbox: [enquiry({ id: 1 })],
			unqualified: [
				enquiry({ id: 2, intent: 'unknown', record_kind: 'unqualified_contact' }),
				openedLease(3)
			],
			disqualified: [enquiry({ id: 4, status: 'disqualified' })]
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.inbox.list('all')
		expect(res.items.map((x) => x.id).sort()).toEqual(['1', '2'])
	})

	it('has no Not real tab: the Inbox never asks for or lists dismissed enquiries', async () => {
		const get = serveInbox({
			inbox: [],
			unqualified: [enquiry({ id: 5, intent: 'unknown', status: 'disqualified' })],
			disqualified: []
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.inbox.list('all')
		// The client removed the tab: nothing could be marked not real, so it was always empty.
		expect(Object.keys(res.lists).sort()).toEqual(['all', 'mine', 'waiting'])
		expect(get.mock.calls.some(([u]) => String(u).includes('status=disqualified'))).toBe(false)
		expect(res.items).toEqual([])
	})

	it('opens only a typed enquiry as a lead: an unqualified contact has no lead type yet', async () => {
		serveInbox({
			inbox: [enquiry({ id: 1 })],
			unqualified: [enquiry({ id: 2, intent: 'unknown', record_kind: 'unqualified_contact' })],
			disqualified: []
		})
		const { crm } = await import('$lib/crm/api')
		const byId = Object.fromEntries((await crm.inbox.list('all')).items.map((x) => [x.id, x]))
		expect(byId['1'].lead_id).toBe(1)
		expect(byId['2'].lead_id).toBeNull()
	})

	const soldOwner = (id: number, soldOn: string, sales: number) =>
		enquiry({
			id,
			intent: 'unknown',
			record_kind: 'unqualified_contact',
			source: 'Owner file · recently sold',
			// The sync leaves recent sellers unassigned, for a manager to route.
			assigned_user_id: null,
			enquiry_date: `${soldOn}T00:00:00+00:00`,
			raw_notes:
				'Sold Marina Gate 1 unit 1204 on 05 Oct 2026 for AED 2,400,000. (+1 more recent sales)',
			criteria: {},
			observed_data: {
				recent_sales: Array.from({ length: sales }, (_, i) => ({
					property_key: `p${i}`,
					building: 'Marina Gate 1',
					unit: String(1204 - i),
					area: 'Dubai Marina',
					property_type: 'Apartment',
					sold_on: soldOn,
					price_aed: 2_400_000
				}))
			}
		})

	it('shows a recently sold owner in the Inbox with their sale', async () => {
		serveInbox({ inbox: [], unqualified: [soldOwner(9, '2026-10-05', 2)], disqualified: [] })
		const { crm } = await import('$lib/crm/api')
		const [item] = (await crm.inbox.list('all')).items
		expect(item.text).toMatch(/^Sold Marina Gate 1 unit 1204 on 05 Oct 2026/)
		expect(item.want_line).toBe(
			'Recently sold · 2 sales · latest 5 Oct · AED 2.4m · Cash in hand: mortgage unknown'
		)
		// From the agency's owner file, not an inbound enquiry.
		expect(item.line).toBe('vv')
	})

	it('loads every Inbox tab at once, so switching tabs needs no new request', async () => {
		const get = serveInbox({
			inbox: [enquiry({ id: 1 })],
			unqualified: [soldOwner(2, '2026-10-07', 1)],
			disqualified: [enquiry({ id: 3, status: 'disqualified' })]
		})
		const { crm } = await import('$lib/crm/api')
		const res = await crm.inbox.list('all')
		const calls = get.mock.calls.length
		expect(res.lists.all.map((x) => x.id)).toEqual(['1', '2'])
		// Enquiry 1 is assigned to the signed-in agent; the recent seller waits for a manager.
		expect(res.lists.mine.map((x) => x.id)).toEqual(['1'])
		expect(res.lists.waiting.map((x) => x.id)).toEqual(['2'])
		expect(get.mock.calls.length).toBe(calls)
	})

	it('asks for Inbox items within the chosen window, recent sellers up to 1,000', async () => {
		const get = serveInbox({ inbox: [], unqualified: [], disqualified: [] })
		const { crm } = await import('$lib/crm/api')
		await crm.inbox.list('all', 60)
		const unqualified = get.mock.calls
			.map(([url]) => String(url))
			.find((u) => u.includes('workspace=unqualified'))
		expect(unqualified).toContain('within_days=60')
		expect(unqualified).toContain('limit=1000')
	})

	it('shows what a recent seller made on the sale, from their purchase price', async () => {
		const sold = soldOwner(9, '2026-09-30', 1)
		sold.observed_data = {
			recent_sales: [
				{
					sold_on: '2026-09-30',
					price_aed: 1_085_000,
					bought_on: '2024-10-04',
					bought_price_aed: 650_000,
					est_cash_in_hand_aed: 695_000
				}
			]
		}
		const lost = soldOwner(10, '2026-10-08', 1)
		lost.observed_data = {
			recent_sales: [
				{
					sold_on: '2026-10-08',
					price_aed: 1_390_000,
					bought_on: '2024-09-26',
					bought_price_aed: 1_472_828
				}
			]
		}
		serveInbox({ inbox: [], unqualified: [sold, lost], disqualified: [] })
		const { crm } = await import('$lib/crm/api')
		const byId = Object.fromEntries((await crm.inbox.list('all')).items.map((x) => [x.id, x]))
		expect(byId['9'].want_line).toBe(
			'Recently sold · 1 sale · latest 30 Sep · AED 1.08m · Profit +AED 435,000 · Est. cash in hand ≈ AED 695,000'
		)
		expect(byId['10'].want_line).toBe(
			'Recently sold · 1 sale · latest 8 Oct · AED 1.39m · Loss −AED 82,828 · Cash in hand: mortgage unknown'
		)
	})

	it('lets a recently sold owner be approved as a buyer, but not a normal enquiry', async () => {
		serveInbox({
			inbox: [enquiry({ id: 1, intent: 'unknown', record_kind: 'unqualified_contact' })],
			unqualified: [soldOwner(9, '2026-10-09', 1)],
			disqualified: []
		})
		const { crm } = await import('$lib/crm/api')
		const byId = Object.fromEntries((await crm.inbox.list('all')).items.map((x) => [x.id, x]))
		expect(byId['9'].can.approve).toBe(true)
		expect(byId['9'].lead_id).toBeNull()
		expect(byId['1'].can.approve).toBe(false)
	})

	it('approves through the backend into a buyer lead that keeps the recent sale', async () => {
		serve({})
		const approved = soldOwner(9, '2026-10-09', 1)
		approved.intent = 'buy'
		approved.record_kind = 'opportunity'
		const post = vi.spyOn(client, 'post').mockResolvedValue(approved)
		const { crm } = await import('$lib/crm/api')
		const res = await crm.inbox.approve('9')
		expect(post).toHaveBeenCalledWith('/api/v1/crm/inbound/enquiries/9/approve-buyer')
		expect(res.data.lead_type).toBe('buyer')
		expect(res.data.recent_sales?.[0].price_aed).toBe(2_400_000)
	})

	it('asks for a brief instead of matching a lead without one', async () => {
		const approved = soldOwner(9, '2026-10-09', 1)
		approved.intent = 'buy'
		approved.record_kind = 'opportunity'
		approved.qualification_complete = false
		serve({ '/api/v1/crm/inbound/enquiries/9': approved })
		const post = vi.spyOn(client, 'post')
		const res = await backend.leadMatches(9)
		// No budget, area or type yet: matching would be refused, so it is not asked for.
		expect(res.needs_brief).toBe(true)
		expect(res.tiers).toEqual([])
		expect(post).not.toHaveBeenCalled()
	})

	it('lists recent sellers newest sale first', async () => {
		serveInbox({
			inbox: [],
			unqualified: [soldOwner(1, '2026-08-20', 1), soldOwner(2, '2026-10-07', 1)],
			disqualified: []
		})
		const { crm } = await import('$lib/crm/api')
		expect((await crm.inbox.list('all')).items.map((x) => x.id)).toEqual(['2', '1'])
	})

	it('offers no Ask, Release or Dismiss: the handout system is not on the backend yet', async () => {
		serveInbox({
			inbox: [enquiry({ id: 1, assigned_user_id: null })],
			unqualified: [],
			disqualified: []
		})
		const { crm } = await import('$lib/crm/api')
		const [item] = (await crm.inbox.list('waiting')).items
		expect(item.state).toBe('waiting')
		expect(Object.values(item.can).some(Boolean)).toBe(false)
	})
})

describe('Assets › Renewals (/api/v1/crm/renewals)', () => {
	const params = {
		area: '',
		window: '' as const,
		property_type: '',
		project: '',
		building: '',
		limit: 50
	}
	const renewalsResponse = { leads: [lease()], total: 1, property_types: ['Apartment'] }

	it('opens on vacant units: the vacant window is the default the tab asks for', async () => {
		const get = serve({ '/api/v1/crm/renewals': renewalsResponse })
		const { crm } = await import('$lib/crm/api')
		const { ui } = await import('$lib/crm/stores/ui.svelte')
		await crm.renewals.list({ ...params, window: ui.renewalWindow })
		const url = String(get.mock.calls[0][0])
		expect(ui.renewalWindow).toBe('vacant')
		expect(url).toContain('window=vacant')
	})

	it("asks for every area unless one is picked: the full dataset, not the agent's areas", async () => {
		const get = serve({ '/api/v1/crm/renewals': renewalsResponse })
		const { crm } = await import('$lib/crm/api')
		const res = await crm.renewals.list(params)
		expect(String(get.mock.calls[0][0])).not.toContain('area=')
		expect(res.items[0]).toMatchObject({ id: 'lease-1', unit: 'Bloom Towers', owner: null })
		expect(res.property_types).toEqual(['Apartment'])
	})

	it('passes the abort signal so a filter change drops the previous request', async () => {
		const get = serve({ '/api/v1/crm/renewals': renewalsResponse })
		const { crm } = await import('$lib/crm/api')
		const controller = new AbortController()
		await crm.renewals.list(params, controller.signal)
		expect(get.mock.calls[0][1]).toMatchObject({ signal: controller.signal })
	})
})

describe('CRM areas with no backend yet', () => {
	it('read as empty instead of showing records nobody stored', async () => {
		const { crm } = await import('$lib/crm/api')
		const get = vi.spyOn(client, 'get')
		expect((await crm.listings.list('mine')).items).toEqual([])
		expect(await crm.notifications.list()).toEqual([])
		expect(get).not.toHaveBeenCalled()
	})

	it('refuse writes with a 501 so no screen reports a save that did not happen', async () => {
		const { crm } = await import('$lib/crm/api')
		await expect(
			crm.listings.create({ address: 'JVC', price_aed: 1 } as never)
		).rejects.toMatchObject({ status: 501 })
	})

	it("fill Home's new leads and the sidebar count from real leads", async () => {
		serve({
			'/api/v1/crm/inbound/enquiries': {
				enquiries: [enquiry({ id: 1 }), enquiry({ id: 2, status: 'contacted' })],
				total: 2,
				summary: {}
			}
		})
		const { crm } = await import('$lib/crm/api')
		const home = await crm.home('2026-10-07')
		expect(home.new_leads.map((l) => l.id)).toEqual([1])
		expect(home.week.map((d) => d.date)).toEqual([
			'2026-10-05',
			'2026-10-06',
			'2026-10-07',
			'2026-10-08',
			'2026-10-09',
			'2026-10-10',
			'2026-10-11'
		])
		expect((await crm.counts()).new_leads).toBe(1)
	})
})

describe('CRM company listing source', () => {
	it('stops buyer matching against a company by clearing the source', async () => {
		const del = vi.spyOn(client, 'delete').mockResolvedValue(undefined as never)
		await backend.clearCompanyListingSource()
		expect(del).toHaveBeenCalledWith('/api/v1/crm/company-listings/source')
	})
})

describe('Tenant matches respect the saved move-in date', () => {
	const tenant = (criteria: Record<string, unknown>) =>
		enquiry({
			id: 11,
			intent: 'rent',
			status: 'qualified',
			qualification_complete: true,
			criteria: {
				locations: ['JVC'],
				property_type: 'Apartment',
				budget_max_aed: 120_000,
				...criteria
			}
		})
	const unitMatch = {
		id: 1,
		target_type: 'unit',
		target_key: 'u1',
		state: 'suggested',
		fit: 'near',
		title: 'Binghatti Gate · Unit 1204',
		subtitle: '2 · AED 110,000',
		reasons: ['Lease ends 15 Jan 2027, before move-in 1 Feb 2027'],
		missing_fields: [],
		snapshot: {},
		generated_at: new Date().toISOString()
	}
	const matches = (extra: Record<string, unknown>) => ({
		enquiry_id: 11,
		listing_fresh: true,
		lanes: { company: [], owners: [], units: [unitMatch], listings: [], offplan: [], demand: [] },
		...extra
	})

	it('holds tenant matches to the move-in date and counts what frees up later', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries/11': tenant({ move_in: '2027-02-01' }),
			'/api/v1/crm/inbound/enquiries/11/matches': matches({
				move_in: '2027-02-01',
				hidden_after: { units: 2 }
			})
		})
		const res = await backend.leadMatches(11)
		expect(res.move_by).toBe('2027-02-01')
		const units = res.tiers.find((t) => t.id === 'units')
		expect(units?.sub).toBe('1 found · 2 free after Mon 1 Feb')
		expect(units?.hidden_after).toBe(0)
		expect(res.brief).toContainEqual({ k: 'Move-in', v: '1 Feb 2027' })
	})

	it('matches a tenant with no move-in date as before', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries/11': tenant({}),
			'/api/v1/crm/inbound/enquiries/11/matches': matches({})
		})
		const res = await backend.leadMatches(11)
		expect(res.move_by).toBeNull()
		expect(res.tiers.some((t) => t.sub.includes('free after'))).toBe(false)
	})

	it('shows an old free-text move-in as it was written', async () => {
		serve({
			'/api/v1/crm/inbound/enquiries/11': tenant({ move_in: 'ASAP' }),
			'/api/v1/crm/inbound/enquiries/11/matches': matches({ move_in: '2026-11-03' })
		})
		const res = await backend.leadMatches(11)
		expect(res.brief).toContainEqual({ k: 'Move-in', v: 'ASAP' })
	})
})

it('preserves renewal paging and resolves the owner by unit identity rather than event identity', async () => {
	const get = serve({
		'/api/v1/crm/renewals': {
			leads: [lease({ lead_id: 'event-id', unit_candidate_key: 'unit-key' })],
			owners: {
				'unit-key': { name: 'Resolved Owner', phone: '+971500000001', source: 'owner_import' }
			},
			total: 1
		}
	})
	const result = await backend.listRenewals({
		area: '',
		window: '',
		property_type: '',
		project: '',
		building: '',
		limit: 50,
		offset: 50,
		owner: 'known'
	})
	expect(get.mock.calls[0][0]).toContain('offset=50')
	expect(get.mock.calls[0][0]).toContain('owner=known')
	expect(result.items[0]).toMatchObject({
		id: 'event-id',
		owner: { name: 'Resolved Owner', phone: '+971500000001' }
	})
})

it('does not claim known-owner filtering when an older API omits its owners map', async () => {
	serve({ '/api/v1/crm/renewals': { leads: [lease()], total: 1 } })
	const result = await backend.listRenewals({
		area: '',
		window: '',
		property_type: '',
		project: '',
		building: '',
		limit: 50
	})
	expect(result.owner_filter_supported).toBe(false)
	expect(result.items).toHaveLength(1)
})
