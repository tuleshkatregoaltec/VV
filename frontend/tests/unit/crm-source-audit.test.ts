import { render } from 'svelte/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { getOwner, listOwnerImportDetails, listOwners } from '$lib/crm/api/backend'
import type { OwnerHistorySummary, SourceAuditSummary } from '$lib/crm/api/types'
import OwnerHistorySummaryCard from '$lib/crm/components/owners/OwnerHistorySummary.svelte'
import SourceAuditSummaryCard from '$lib/crm/components/owners/SourceAuditSummary.svelte'

const audit: SourceAuditSummary = {
	mode: 'source_only',
	import_count: 1,
	reference_count: 17,
	owner_candidate_reference_count: 11,
	bank_reference_count: 2,
	excluded_nonownership_reference_count: 1,
	review_reference_count: 2,
	excluded_scope_reference_count: 1,
	source_row_count: 83,
	disposition_counts: {
		latest_recorded_buyer_candidate: 11,
		possible_mortgage_or_bank_acquisition: 2,
		excluded_possible_nonownership_transaction: 1,
		property_extent_requires_review: 2,
		excluded_whole_building_or_project_context: 1
	}
}

afterEach(() => vi.restoreAllMocks())

describe('workbook reference counts stay separate from candidate people', () => {
	it('keeps the audit through Owners paging and filters without replacing people totals', async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.includes('/owner-workspaces')) return [] as never
			return {
				owners: [],
				total: 6,
				summary: {},
				source_audit: audit
			} as never
		})
		const owners = await listOwners({ tab: 'review', area: 'JVC', offset: 50 })
		expect(owners.source_audit).toEqual(audit)
		expect(owners.on_file).toBe(6)
		expect(owners.page.total).toBe(6)
		expect(owners.page.offset).toBe(50)
	})

	it('preserves the audited import summary alongside the historical row counts', async () => {
		vi.spyOn(client, 'get').mockResolvedValue([
			{
				id: 9,
				name: 'Audited workbook',
				original_filename: 'audit.json',
				status: 'completed',
				created_at: '2026-10-26T12:00:00Z',
				list_id: 4,
				summary: { total_rows: 83, candidate_rows: 29, source_audit: audit }
			}
		])
		const [detail] = await listOwnerImportDetails()
		expect(detail.source_audit).toEqual(audit)
		expect(detail.counts.rows).toBe(83)
		expect(detail.counts.kept).toBe(29)
	})

	it('renders API classifications and source rows without presenting verified property totals', () => {
		const html = render(SourceAuditSummaryCard, { props: { summary: audit } }).body.replaceAll(
			/ class="[^"]*"/g,
			''
		)
		for (const [label, count] of [
			['Workbook references', 17],
			['Owner-candidate references', 11],
			['Possible mortgage / bank acquisition', 2],
			['Non-ownership references (excluded)', 1],
			['References needing review', 2],
			['Out-of-scope references (excluded)', 1]
		]) {
			expect(html).toContain(`<dt>${label}</dt><dd>${count}</dd>`)
		}
		expect(html).toMatch(/<details[^>]*>\s*<summary[^>]*>Workbook source audit<\/summary>/)
		expect(html).not.toMatch(/<details[^>]*\sopen(?:[\s=>])/)
		expect(html).toContain('83 source rows across 1 import')
		expect(html).toContain('Workbook only — transaction matching not run')
		expect(html).toContain('DXBI sales evidence was not checked')
		expect(html).toContain('not people or verified physical properties')
		expect(html).toContain('Latest recorded buyer candidate')
		expect(html).toContain('Property extent needs review')
		expect(html).not.toContain('latest_recorded_buyer_candidate')
		expect(html).not.toContain('possible_mortgage_or_bank_acquisition')
		const changed = render(SourceAuditSummaryCard, {
			props: { summary: { ...audit, reference_count: 18, review_reference_count: 3 } }
		}).body.replaceAll(/ class="[^"]*"/g, '')
		expect(changed).toContain('<dt>Workbook references</dt><dd>18</dd>')
		expect(changed).toContain('<dt>References needing review</dt><dd>3</dd>')
	})
})

describe('owner source phone numbers', () => {
	it('retains all source numbers beyond the two legacy fields without duplicating numbers', async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.includes('/owner-workspaces') || url.includes('/contact-imports')) return [] as never
			return {
				owner_key: 'source-owner',
				contact_name: 'Source owner',
				highest_ownership_status: 'probable_current_owner',
				phone_numbers: ['+971500000001', '+971500000002', '+971500000003'],
				phone_primary: '+971500000001',
				phone_alternate: '+971500000004',
				properties: []
			} as never
		})
		const owner = await getOwner('source-owner')
		expect(owner.phone_numbers).toEqual([
			'+971500000001',
			'+971500000002',
			'+971500000003',
			'+971500000004'
		])
		expect(owner.tag).toBe('Possible current owner')
	})
})

describe('source plots and villas retain their recorded identity', () => {
	it('labels blank-unit references with land or building identifiers and preserves square metres', async () => {
		const sourceReference = {
			reference_id: 'plot-reference',
			kind: 'land',
			source_key: ['Project', 'Land 23', 'DM 4'],
			land_number: '23',
			building_number: '',
			dm_sub_number: '4',
			size_sqm: '123.45',
			disposition: 'latest_recorded_buyer_candidate'
		}
		const property = {
			property_key: 'plot',
			project_name: 'Recorded project',
			building_name: '',
			area_name: 'Recorded master project',
			unit_number: '',
			property_type: 'Land',
			ownership_status: 'probable_current_owner',
			confidence_score: 50,
			match_reason: 'Workbook only',
			source_reference: sourceReference
		}
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.includes('/owner-workspaces') || url.includes('/contact-imports')) return [] as never
			return {
				owner_key: 'plot-owner',
				contact_name: 'Source owner',
				highest_ownership_status: 'probable_current_owner',
				properties: [
					property,
					{
						...property,
						property_key: 'villa',
						property_type: 'Villa',
						source_reference: { ...sourceReference, land_number: '', building_number: '88' }
					}
				]
			} as never
		})
		const owner = await getOwner('plot-owner')
		expect(owner.units).toEqual([
			'Recorded project · Land 23 · DM sub 4',
			'Recorded project · Building 88 · DM sub 4'
		])
		expect(owner.unit_rows[0].number).toBe('')
		expect(owner.unit_rows[0].area).toBe('Recorded master project')
		expect(owner.unit_rows[0].source_reference).toEqual(sourceReference)
		expect(owner.unit_rows[0].source_reference?.size_sqm).toBe('123.45')
		expect(owner.unit_rows[0].size_sqft).toBeNull()
	})
})

describe('source-only assessments are intentional rather than an outage', () => {
	const summary: OwnerHistorySummary = {
		source_event_count: 4,
		identifiable_property_count: 2,
		owner_property_count: 3,
		verified_current_count: 0,
		probable_current_count: 3,
		former_count: 0,
		unresolved_count: 0,
		invalid_identity_source_count: 0,
		legacy_source_event_count: 0,
		resolver_versions: {},
		warehouse_status: 'not_requested',
		checked_at: null
	}

	it('does not imply a warehouse outage or a sales check for a source-only summary', () => {
		const html = render(OwnerHistorySummaryCard, {
			props: { summary, scope: 'This import' }
		}).body
		expect(html).toContain('Workbook only — transaction matching not run')
		expect(html).toContain('DXBI sales evidence was not checked')
		expect(html).toContain('Identified source property groups')
		expect(html).toMatch(/<details[^>]*>\s*<summary[^>]*>Evidence and counting details<\/summary>/)
		expect(html).not.toMatch(/<details[^>]*\sopen(?:[\s=>])/)
		expect(html).not.toContain('temporarily unavailable')
		expect(html).not.toContain('Checked against available sales')
	})

	it('keeps historical associations visible without presenting them as additional review cases', () => {
		const html = render(OwnerHistorySummaryCard, {
			props: {
				summary: {
					...summary,
					unresolved_count: 54_479,
					invalid_identity_source_count: 7,
					unverified_former_count: 12
				},
				scope: 'This import'
			}
		}).body
		expect(html).toContain('Source associations')
		expect(html).toContain('Other historical/source associations')
		expect(html).toContain('54,479')
		expect(html).toContain('not additional reference-review cases')
		expect(html).toContain('The Workbook source audit gives the audited reference classifications')
		expect(html).toContain('Buyer transaction matches (not checked)')
		expect(html).toContain('Former-owner associations (not rechecked)')
		expect(html).toContain('12 historical seller-claim associations')
		expect(html).not.toContain('Links needing review')
		expect(html).not.toContain('Review people with unresolved evidence')
		expect(html).not.toContain('also appear in the review queue')
		expect(html).not.toContain('seller claims are included in links needing review')
		expect(html).not.toContain('rechecks the available evidence')
	})

	it('retains the existing unavailable-evidence notice for normal imports', () => {
		const html = render(OwnerHistorySummaryCard, {
			props: {
				summary: { ...summary, warehouse_status: 'unavailable', unresolved_count: 3 },
				scope: 'All imports'
			}
		}).body
		expect(html).toContain('Sales evidence is temporarily unavailable')
		expect(html).not.toContain('Workbook only')
		expect(html).toContain('Links needing review')
		expect(html).toContain('Review people with unresolved evidence')
	})
})

describe('transaction matching audit', () => {
	it('shows matched references separately from distinct transaction properties and people', () => {
		const html = render(SourceAuditSummaryCard, {
			props: {
				summary: {
					...audit,
					mode: 'source_transaction_matched',
					matched_reference_count: 9,
					matched_registry_property_count: 8,
					unmatched_reference_count: 4,
					ambiguous_reference_count: 2,
					excluded_match_reference_count: 2,
					current_owner_association_count: 7,
					former_owner_association_count: 5
				}
			}
		}).body.replaceAll(/ class="[^"]*"/g, '')
		expect(html).toContain('<dt>Source references matched to transactions</dt><dd>9</dd>')
		expect(html).toContain('<dt>Distinct transaction properties matched</dt><dd>8</dd>')
		expect(html).toContain('<dt>Former owner–property associations</dt><dd>5</dd>')
		expect(html).toContain(
			'9 matched + 4 unmatched + 2 ambiguous + 2 excluded = 17 workbook references'
		)
		expect(html).toContain('Workbook classifications before transaction matching')
		expect(html).toContain('Unmatched candidates remain visible')
		expect(html).toContain('do not verify the current named title holder')
		expect(html).not.toContain('matching not run')
	})
})

describe('unverified owner associations remain visible with their recorded role', () => {
	const property = (status: string, match: string, basis = 'workbook_only') => ({
		property_key: 'source:1',
		ownership_status: status,
		confidence_score: 60,
		match_reason: 'Workbook buyer history',
		area_name: 'Dubai Hills Estate',
		project_name: 'Example',
		building_name: 'Example Tower',
		unit_number: '101',
		property_type: 'Flat',
		source_reference: {
			reference_id: 'reference:1',
			kind: 'unit',
			source_key: ['unit', '101'],
			disposition: 'latest_recorded_buyer_candidate',
			transaction_match_status: match,
			ownership_evidence_basis: basis
		}
	})
	it.each([
		['probable_current_owner', 'unmatched', 'workbook_only', 'Unverified current candidate'],
		['former_owner', 'ambiguous', 'workbook_only', 'Unverified former owner'],
		['former_owner', 'matched', 'workbook_only', 'Unverified former owner'],
		['former_owner', 'matched', 'transaction_supported', 'Former owner']
	])('labels %s / %s / %s accurately', async (status, match, basis, label) => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.includes('/owner-workspaces') || url.includes('/contact-imports')) return [] as never
			return {
				owner_key: 'source-owner',
				contact_name: 'Source Owner',
				highest_ownership_status: status,
				properties: [property(status, match, basis)]
			} as never
		})
		const result = await getOwner('source-owner')
		expect(result.tag).toBe(label)
		expect(result.unit_rows[0].status_chip.label).toBe(label)
		expect(result.unit_rows[0].check?.result.label).toBe(label)
	})
	it('keeps mixed portfolios explicit without labeling all properties unmatched', async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
			if (url.includes('/owner-workspaces') || url.includes('/contact-imports')) return [] as never
			return {
				owner_key: 'source-owner',
				contact_name: 'Source Owner',
				highest_ownership_status: 'probable_current_owner',
				properties: [
					property('probable_current_owner', 'matched', 'transaction_supported'),
					{ ...property('former_owner', 'unmatched'), property_key: 'source:2' }
				]
			} as never
		})
		const result = await getOwner('source-owner')
		expect(result.tag).toBe('Includes unverified properties')
		expect(result.unit_rows.map((p) => p.status_chip.label)).toEqual([
			'Possible current owner',
			'Unverified former owner'
		])
	})
})
