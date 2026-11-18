import { describe, expect, it, vi } from 'vitest'
import { client } from '$lib/api/client'
import { crm } from '$lib/crm/api'
import { createPresentationCrm } from '$lib/crm/api/presentation'

vi.mock('$env/dynamic/public', () => ({ env: {} }))
const make = () => createPresentationCrm(crm, '2026-11-02')

describe('isolated CRM presentation', () => {
	it('populates the main screens without consulting live records', async () => {
		const network = vi
			.spyOn(client, 'get')
			.mockRejectedValue(new Error('Live data must not be read'))
		try {
			const demo = make()
			expect((await demo.leads.list({})).items.length).toBeGreaterThan(50)
			expect((await demo.owners.list({ tab: 'all' })).items).toHaveLength(24)
			expect((await demo.listings.list('company')).items).toHaveLength(30)
			expect((await demo.deals.list('conveyancing')).items).toHaveLength(14)
			expect((await demo.events.list('2026-10-01', '2026-12-01')).length).toBeGreaterThan(20)
			expect((await demo.inbox.list('all')).items).toHaveLength(16)
			expect((await demo.imports.ownerDetails()).length).toBeGreaterThan(0)
			expect(network).not.toHaveBeenCalled()
		} finally {
			network.mockRestore()
		}
	})
	it('rejects writes and outbound actions instead of falling through to real APIs', async () => {
		const demo = make()
		for (const action of [
			() => demo.leads.addNote(900001, 'Never persist this'),
			() => demo.deals.move('PD-1001', 'next', 0),
			() => demo.owners.sendMarketUpdate('PO-1'),
			() => demo.imports.removeOwners(950001),
			() => demo.events.remove(910001),
			() => demo.notifications.read(),
			() => demo.companyListings.clearSource()
		])
			await expect(action()).rejects.toMatchObject({ status: 405 })
		expect((await demo.leads.events(900001))[0].text).not.toContain('Never persist this')
	})
	it('keeps counts and commission totals consistent with displayed rows', async () => {
		const demo = make()
		const active = await demo.leads.list({})
		const lost = await demo.leads.list({ lost: true })
		expect(active.items.length + lost.items.length).toBe(72)
		expect(active.counts.all).toBe(active.items.length)
		const pipeline = await demo.deals.list('conveyancing')
		expect(pipeline.counts.sale + pipeline.counts.rent).toBe(pipeline.counts.open)
		const deals = await demo.deals.list('commission')
		expect(deals.totals.gross).toBe(
			deals.items.reduce((sum, row) => sum + row.commission.amounts.gross, 0)
		)
		for (const deal of deals.items) {
			expect(deal.commission.amounts.agent + deal.commission.amounts.agency).toBe(
				deal.commission.amounts.net
			)
			if (deal.lead_id === null || deal.listing_id === null) throw new Error('Missing fixture link')
			expect((await demo.leads.get(deal.lead_id)).name).toBe(deal.client)
			expect((await demo.listings.get(deal.listing_id)).unit).toBe(deal.unit)
			const detail = await demo.deals.get(deal.id)
			expect(detail.documents.received).toHaveLength(detail.docs_received)
		}
		const home = await demo.home('2026-11-02')
		expect(home.facts.events_today).toBe(home.day.length)
		expect(home.new_leads.length).toBe(home.counters.new_leads)
	})
	it('keeps fictional contact details non-deliverable and returns independent records', async () => {
		const demo = make()
		const lead = await demo.leads.get(900001)
		expect(lead.email).toMatch(/@example\.com$/)
		expect(lead.phone).toBe('')
		lead.name = 'Changed in UI'
		expect((await demo.leads.get(900001)).name).not.toBe('Changed in UI')
	})
	it('filters and opens linked owner, property and lead records', async () => {
		const demo = make()
		const leads = await demo.leads.list({ area: 'Dubai Marina', lead_type: 'buyer' })
		expect(leads.items.length).toBeGreaterThan(0)
		expect(leads.items.every((l) => l.area === 'Dubai Marina' && l.lead_type === 'buyer')).toBe(
			true
		)
		for (const owner of (await demo.owners.list({ tab: 'all' })).items) {
			const detail = await demo.owners.get(owner.id)
			expect(detail.units_total).toBe(detail.unit_rows.length)
			for (const unit of detail.unit_rows)
				expect((await demo.listings.get(unit.key)).owner).toBe(detail.name)
		}
	})
	it('keeps area import rows, property totals and owner provenance scoped to the selected file', async () => {
		const demo = make()
		const files = await demo.imports.ownerDetails()
		expect(files).toHaveLength(6)
		for (const [index, area] of [
			'Dubai Marina',
			'Downtown Dubai',
			'Business Bay',
			'Dubai Hills Estate',
			'Palm Jumeirah'
		].entries()) {
			const id = 950010 + index
			const file = files.find((file) => file.id === id)
			const rows = await demo.imports.ownerRows(id, { status: null, search: '', offset: 0 })
			expect(rows.rows).toHaveLength(5)
			expect(rows.rows.every((row) => row.area === area)).toBe(true)
			expect(file?.counts.rows).toBe(rows.total)
			expect(file?.counts.ownerMatch?.headline.units).toBe(rows.total)
			expect(file?.counts.ownerMatch?.sales?.withUnit).toBe(rows.total)
			expect(file?.counts.ownerMatch?.sales?.withoutUnit).toBe(0)
			const properties = await demo.imports.ownerProperties(id, { search: '', offset: 0 })
			expect(properties.total).toBe(rows.total)
			expect(properties.rows.every((row) => row.area === area)).toBe(true)
			expect((await demo.owners.historySummary(id)).owner_property_count).toBe(rows.total)
			for (const row of rows.rows) {
				expect(row.matchedSale?.amount_aed).toBe(row.price)
				expect(row.matchedSale?.unit).toBe(row.unit)
				const owner = await demo.owners.get(row.ownerKey)
				expect(owner.imported_from.some((source) => source.importId === id)).toBe(true)
			}
		}
		expect((await demo.owners.historySummary()).source_event_count).toBe(55)
		expect((await demo.owners.historySummary()).identifiable_property_count).toBe(30)
	})
	it('does not substitute another import when an unknown id or unmatched filter is selected', async () => {
		const demo = make()
		await expect(
			demo.imports.ownerRows(1, { status: null, search: '', offset: 0 })
		).rejects.toMatchObject({ status: 404 })
		const rows = await demo.imports.ownerRows(950010, {
			status: null,
			search: '',
			matchColour: ['amber'],
			offset: 0
		})
		expect(rows.total).toBe(0)
		const search = await demo.imports.ownerRows(950010, { status: null, search: 'Palm', offset: 0 })
		expect(search.total).toBe(0)
	})
})
