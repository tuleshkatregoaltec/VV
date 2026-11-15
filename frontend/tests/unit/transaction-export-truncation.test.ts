import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { exportTruncationNotice, transactions } from '$lib/api/transactions'

// The CSV export used to stop at 50,000 rows without saying so (audit 2026-11-15). The API now
// reports the cap in X-Export-* headers and the page tells the user.
function exportResponse(headers: Record<string, string>) {
	return new Response(new Blob(['Transaction ID\n']), { status: 200, headers })
}

describe('transaction exports', () => {
	afterEach(() => vi.restoreAllMocks())

	it('reads the truncation headers next to the file', async () => {
		const getSpy = vi.spyOn(client, 'get').mockResolvedValue(
			exportResponse({
				'X-Export-Rows': '50000',
				'X-Export-Matching-Rows': '73412',
				'X-Export-Truncated': 'true'
			})
		)

		const file = await transactions.exportSales({ timeframe_days: 30 }, 'csv')

		expect(getSpy.mock.calls[0][1]).toEqual({ returnResponse: true })
		expect(file.truncated).toBe(true)
		expect(file.rows).toBe(50000)
		expect(file.matchingRows).toBe(73412)
		expect(await file.blob.text()).toBe('Transaction ID\n')
		expect(exportTruncationNotice(file, 'sales')).toBe(
			'This file holds the newest 50,000 of 73,412 matching sales. Narrow the filters to export the rest.'
		)
	})

	it('says nothing when the whole selection fits', async () => {
		vi.spyOn(client, 'get').mockResolvedValue(
			exportResponse({
				'X-Export-Rows': '12',
				'X-Export-Matching-Rows': '12',
				'X-Export-Truncated': 'false'
			})
		)

		const file = await transactions.exportRentals({}, 'xlsx')

		expect(file.truncated).toBe(false)
		expect(exportTruncationNotice(file, 'leases')).toBeNull()
	})
})
