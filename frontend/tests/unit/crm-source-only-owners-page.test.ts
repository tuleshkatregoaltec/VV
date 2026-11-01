import { render } from 'svelte/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OwnerListResponse } from '$lib/crm/api/types'
import { ui } from '$lib/crm/stores/ui.svelte'
import OwnersPage from '../../src/routes/crm/owners/+page.svelte'

const data = vi.hoisted(() => ({
	owners: null as OwnerListResponse | null,
	requestedTab: '',
	requestedOwnership: ''
}))

vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/crm/owners') } }))
vi.mock('@tanstack/svelte-query', async (importOriginal) => ({
	...(await importOriginal<typeof import('@tanstack/svelte-query')>()),
	createQuery: (options: () => { queryKey: readonly unknown[] }) => {
		const key = options().queryKey
		if (key[4] === 'owners') {
			data.requestedTab = (key[5] as { tab: string }).tab
			data.requestedOwnership = (key[5] as { ownership: string }).ownership
		}
		return {
			data: key[4] === 'owners' ? data.owners : [],
			isPlaceholderData: false,
			isError: false
		}
	}
}))

afterEach(() => {
	ui.ownerTab = 'all'
	ui.ownerOwnership = 'current'
	data.owners = null
	data.requestedTab = ''
})

describe('Owners labels unverified people separately from audited reference review cases', () => {
	const owners: OwnerListResponse = {
		items: [],
		pageFiltered: false,
		areas: [],
		page: { offset: 0, limit: 10, total: 37, loaded: 0 }
	}

	it('retains the candidate filter while explaining the separate audit review count', () => {
		ui.ownerTab = 'review'
		data.owners = {
			...owners,
			source_audit: {
				mode: 'source_only',
				reference_count: 17,
				owner_candidate_reference_count: 11,
				review_reference_count: 2
			}
		}
		const html = render(OwnersPage).body
		expect(html).toContain('Candidates')
		expect(html).not.toContain('Transaction matching was not run')
		expect(html).not.toContain('Needs review')
		expect(data.requestedTab).toBe('review')
	})

	it('offers exactly current and former ownership with current selected by default', () => {
		data.owners = {
			...owners,
			source_audit: { mode: 'source_transaction_matched', reference_count: 17 }
		}
		const html = render(OwnersPage).body
		expect(html).toContain('aria-label="Ownership"')
		expect(html).toContain('value="current"')
		expect(html).toContain('Current owners')
		expect(html).toContain('value="former"')
		expect(html).toContain('Former owners')
		expect(html).not.toContain('most recent')
		expect(html).not.toContain('Candidates')
		expect(data.requestedOwnership).toBe('current')
	})

	it('preserves the normal review label and guidance without a workbook-only audit', () => {
		ui.ownerTab = 'review'
		data.owners = owners
		const html = render(OwnersPage).body
		expect(html).toContain('Needs review')
		expect(html).not.toContain('Review people with unresolved claims')
		expect(html).not.toContain('Candidates')
		expect(data.requestedTab).toBe('review')
	})
})
