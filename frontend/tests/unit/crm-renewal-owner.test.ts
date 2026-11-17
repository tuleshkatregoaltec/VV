import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type {
	CrmLead,
	CrmLeadDetailResponse,
	CrmLeadImportedContact,
	CrmRenewalOwner
} from '$lib/api/generated/hey-api/types.gen'
import { getRenewal, saveRenewalOwner } from '$lib/crm/api/backend'

afterEach(() => vi.restoreAllMocks())

const lead = {
	lead_id: 'lease-1',
	building_name: 'Bloom Towers',
	unit_number: '216',
	area_name: 'Jumeirah Village Circle',
	property_type: 'Apartment',
	annual_rent_aed: 85_000,
	lease_start: '2025-12-08',
	lease_end: '2026-12-07',
	days_to_expiry: 60,
	lead_reason: 'Lease expires soon.',
	recommended_action: 'Contact the owner once identified.'
} as CrmLead

function claim(
	id: number,
	status: CrmLeadImportedContact['ownership_status']
): CrmLeadImportedContact {
	return {
		claim_id: id,
		list_id: 7,
		list_name: 'Owner file',
		contact_name: `Imported contact ${id}`,
		phone_primary: '+971500000001',
		email_primary: 'imported@example.test',
		ownership_status: status,
		confidence_score: 90,
		match_reason: 'Review sale evidence.',
		source_sheet: 'Owners',
		imported_at: '2026-10-08T00:00:00Z',
		owner_key: `owner-${id}`
	}
}

function serve(owner: CrmRenewalOwner | null, contacts: CrmLeadImportedContact[]) {
	const detail: CrmLeadDetailResponse = {
		lead,
		owner,
		timeline: [],
		next_best_actions: [],
		match_explanation: 'Exact unit history.',
		generated_at: '2026-10-08T00:00:00Z'
	}
	const get = vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		if (url === '/api/v1/crm/leads/lease-1') return detail
		if (url === '/api/v1/crm/leads/lease-1/contacts') return contacts
		throw new Error(`Unexpected GET ${url}`)
	})
	return { detail, contacts, get }
}

describe('renewal owner fields use the canonical server resolution', () => {
	it.each([
		'probable_current_owner',
		'conflicting_claim',
		'unmatched'
	] as const)('keeps an unknown owner blank while retaining %s evidence for review', async (status) => {
		serve(null, [claim(1, status)])
		const renewal = await getRenewal('lease-1')
		expect(renewal.owner).toBeNull()
		expect(renewal.unit).toBe('Bloom Towers · unit 216')
		expect(renewal.owner_evidence).toEqual([
			{
				id: 1,
				name: 'Imported contact 1',
				status,
				reason: 'Review sale evidence.',
				source: 'Owner file'
			}
		])
	})

	it('does not choose the first contact when multiple verified claims are unresolved', async () => {
		const { get } = serve(null, [
			claim(1, 'verified_current_owner'),
			claim(2, 'verified_current_owner')
		])
		const renewal = await getRenewal('lease-1')
		expect(renewal.owner).toBeNull()
		expect(renewal.owner_evidence).toHaveLength(2)
		expect(get.mock.calls.map(([url]) => url)).not.toContain('/api/v1/crm/workspaces/lease-1')
	})

	it('preserves manual owner values and intentional blanks when imports change', async () => {
		const { contacts } = serve(
			{ name: 'Manual owner', phone: null, email: 'manual@example.test', source: 'workspace' },
			[claim(1, 'verified_current_owner')]
		)
		const before = (await getRenewal('lease-1')).owner
		contacts.splice(0, 1, claim(2, 'verified_current_owner'))
		const after = (await getRenewal('lease-1')).owner
		expect(after).toEqual(before)
		expect(after).toEqual({
			name: 'Manual owner',
			phone: null,
			email: 'manual@example.test',
			source: 'Saved on this lead'
		})
	})

	it('reflects refreshed imported ownership instead of retaining a workspace snapshot', async () => {
		const { detail } = serve(
			{ name: 'Previous owner', phone: null, email: null, source: 'owner_import' },
			[]
		)
		expect((await getRenewal('lease-1')).owner?.name).toBe('Previous owner')
		detail.owner = { name: 'New owner', phone: '+971500000002', source: 'owner_import' }
		expect((await getRenewal('lease-1')).owner).toEqual({
			name: 'New owner',
			phone: '+971500000002',
			email: null,
			source: 'Owner import'
		})
		detail.owner = null
		expect((await getRenewal('lease-1')).owner).toBeNull()
	})

	it('saves trimmed manual fields and returns the authoritative owner after reload', async () => {
		const { detail } = serve(null, [claim(1, 'probable_current_owner')])
		const patch = vi.spyOn(client, 'patch').mockImplementation(async () => {
			detail.owner = { name: 'Typed owner', phone: null, email: null, source: 'workspace' }
			return detail
		})
		const result = await saveRenewalOwner('lease-1', {
			name: ' Typed owner ',
			phone: ' ',
			email: ''
		})
		expect(patch).toHaveBeenCalledWith('/api/v1/crm/workspaces/lease-1', {
			owner_name: 'Typed owner',
			owner_phone: null,
			owner_email: null
		})
		expect(result.data.owner).toMatchObject({ name: 'Typed owner', phone: null, email: null })
		expect(result.data.owner_evidence[0].status).toBe('probable_current_owner')
	})
})
