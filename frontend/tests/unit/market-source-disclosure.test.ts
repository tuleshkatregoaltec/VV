import { render } from 'svelte/server'
import { describe, expect, it } from 'vitest'
import type { CustomChartArtifact, MarketTrendArtifact } from '$lib/chat/artifacts'
import ChatCustomChart from '$lib/components/chat/ChatCustomChartArtifact.svelte'
import ChatMarketTrend from '$lib/components/chat/ChatMarketTrendArtifact.svelte'
import TransactionDetails from '$lib/components/transactions/TransactionDetailsModal.svelte'
import { explainMatch, matchedSaleLine } from '$lib/crm/ownerImportReport'
import { toSaleRow } from '$lib/utils/transactionPages'

const providers = /\b(DLD|DXBI|DXBInteract|Dubai Land Department)\b/i

describe('customer-facing market presentation', () => {
	it('keeps the chart period and downloads without rendering server provider metadata', () => {
		const artifact: CustomChartArtifact = {
			id: 'chart',
			type: 'custom_chart',
			status: 'ready',
			title: 'Sales by month',
			created_at: '2026-10-01',
			data: {
				chart_type: 'bar',
				metric: 'price',
				metric_label: 'Sale price',
				dimension: 'month',
				dimension_label: 'Month',
				data_source: 'DLD sales and DXBInteract (DXBI)',
				points: [{ label: 'October', value: 1500000 }],
				summary: { period_start: '2026-10-01', period_end: '2026-10-31' }
			}
		}
		const { body } = render(ChatCustomChart, { props: { artifact } })
		expect(body).not.toMatch(providers)
		expect(body).toContain('Period:')
		expect(body).toContain('2026-10-01')
		expect(body).toContain('PNG')
		expect(body).toContain('CSV')
	})

	it('keeps market trend values and dates without the hardcoded provider footer', () => {
		const artifact: MarketTrendArtifact = {
			id: 'trend',
			type: 'market_trend',
			status: 'ready',
			title: 'Market trend',
			created_at: '2026-10-01',
			data: {
				total_transactions: 4,
				data: [
					{ date: '2026-10-01', transaction_count: 4, avg_price: 1500000, avg_price_sqft: 1500 }
				]
			}
		}
		const { body } = render(ChatMarketTrend, { props: { artifact } })
		expect(body).not.toMatch(providers)
		expect(body).toContain('Latest average price:')
		expect(body).toContain('2026-10-01')
	})

	it('keeps transaction details and official geography without exposing enrichment providers', () => {
		const transaction = toSaleRow({
			transaction_id: 'T-1',
			transaction_date: '2026-10-01',
			unit_number: '1203',
			building_name: 'Synthetic Tower',
			dld_area: 'Synthetic District',
			project_name: 'Synthetic Project',
			price_aed: 1500000
		} as Parameters<typeof toSaleRow>[0])
		const { body } = render(TransactionDetails, { props: { transaction, onClose: () => {} } })
		expect(body).not.toMatch(providers)
		expect(body).toContain('District')
		expect(body).toContain('Synthetic District')
		expect(body).toContain('1203')
	})

	it.each([
		'DXBI sales evidence was not checked',
		'No DLD sale found',
		"DXBInteract's sale record",
		'Dubai Land Department record unavailable'
	])('keeps legacy diagnostic meaning without provider names: %s', (text) => {
		const result = explainMatch(text)
		expect(result).not.toMatch(providers)
		expect(result).toContain('market data')
	})

	it.each([
		'dxbi',
		'dld',
		'Private future provider'
	])('keeps matched sale evidence without attributing %s', (source) => {
		const line = matchedSaleLine({
			source,
			unit: '1203',
			building: 'Synthetic Tower',
			amount_aed: 1500000,
			date: '2026-10-01'
		})
		expect(line).toContain('1203 · Synthetic Tower · AED 1,500,000')
		expect(line).not.toContain(source)
	})
})
