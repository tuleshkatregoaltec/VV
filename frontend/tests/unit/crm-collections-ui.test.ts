import { render } from 'svelte/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// No DOM environment: decision logic is tested as pure functions, copy and states by server render
// with the query result mocked. Click behaviour in a real browser is covered by the Playwright run.
const q = vi.hoisted(() => ({ byKey: {} as Record<string, unknown> }))

vi.mock('@tanstack/svelte-query', async (orig) => ({
	...(await orig<typeof import('@tanstack/svelte-query')>()),
	createQuery: (fn: () => { queryKey: unknown[] }) => {
		const o = fn()
		return q.byKey[String(o.queryKey[2])] ?? q.byKey.default
	}
}))
vi.mock('$lib/crm/api', () => ({
	crm: {
		collections: {
			removeItem: vi.fn().mockResolvedValue(undefined),
			remove: vi.fn().mockResolvedValue(undefined),
			addItem: vi.fn().mockResolvedValue({}),
			shareLink: vi.fn().mockResolvedValue({ url: 'https://app.test/collections/tok' }),
			update: vi.fn().mockResolvedValue({})
		}
	}
}))
vi.mock('$lib/queries/client', () => ({ getQueryClient: () => qc }))
const qc = vi.hoisted(() => ({
	invalidateQueries: vi.fn().mockResolvedValue(undefined),
	removeQueries: vi.fn()
}))

import { ApiError } from '$lib/api/client'
import { crm } from '$lib/crm/api'
import CollectionEditor from '$lib/crm/components/collections/CollectionEditor.svelte'
import CollectionList from '$lib/crm/components/collections/CollectionList.svelte'
import {
	addListing,
	copyShareLink,
	deleteCollection,
	removeItem
} from '$lib/crm/components/collections/collectionActions'
import {
	addButtonClick,
	canAddToCollection,
	isCollectionFull,
	menuItemState,
	menuRowState
} from '$lib/crm/components/collections/collectionRules'
import { crmKeys } from '$lib/crm/queries'
import { toast } from '$lib/crm/stores/toast.svelte'

const collection = (over: Record<string, unknown> = {}) => ({
	id: 'c1',
	name: 'Marina picks',
	sharing_enabled: false,
	item_count: 1,
	created_by_user_id: 'u1',
	agent_name: 'Sara',
	agent_email: null,
	agent_phone: null,
	created_at: '2026-11-12T10:00:00Z',
	updated_at: '2026-11-12T10:00:00Z',
	items: [
		{
			id: 'i1',
			source: 'property_finder',
			listing_key: '111',
			listing_title: 'Sea view 2BR',
			added_at: '2026-11-12T10:00:00Z',
			listing: { title: 'Sea view 2BR', area_name: 'Marina', price_aed: 2500000, mode: 'sale' }
		}
	],
	...over
})
const ok = (data: unknown) => ({ isPending: false, isError: false, data, refetch: vi.fn() })

beforeEach(() => {
	vi.clearAllMocks()
	q.byKey = {}
})

describe('collections UI', () => {
	it('add_button_does_not_open_listing', () => {
		const stop = vi.fn()
		const open = vi.fn()
		addButtonClick({ stopPropagation: stop } as unknown as Event, open)
		expect(stop).toHaveBeenCalled()
		expect(open).toHaveBeenCalled()
		const a = { company: { broker_id: 'b1' }, matching_company: { broker_id: 'b1' } }
		expect(canAddToCollection(a)).toBe(true)
		expect(canAddToCollection({ ...a, matching_company: { broker_id: 'b2' } })).toBe(false)
		expect(canAddToCollection({ company: { broker_id: 'b1' }, matching_company: null })).toBe(false)
		expect(canAddToCollection({ company: null, matching_company: null })).toBe(false)
	})

	it('add to full collection shows disabled', () => {
		expect(isCollectionFull(50)).toBe(true)
		expect(menuItemState({ item_count: 50 }, false)).toEqual({
			checked: false,
			disabled: true,
			hint: '50 / 50'
		})
		expect(menuItemState({ item_count: 3 }, false).disabled).toBe(false)
		expect(menuItemState({ item_count: 50 }, true)).toMatchObject({ checked: true, disabled: true })
	})

	it('a string-detail 409 shows the friendly collection_full text', async () => {
		vi.mocked(crm.collections.addItem).mockRejectedValueOnce(
			new ApiError('collection_full', 409, undefined, { detail: 'collection_full' })
		)
		expect(await addListing('c1', '111')).toBeNull()
		expect(toast.message).toBe('This collection is full (50 / 50).')
	})

	it('copy link writes share url to clipboard', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined)
		await copyShareLink('c1', writeText)
		expect(crm.collections.shareLink).toHaveBeenCalledWith('c1')
		expect(writeText).toHaveBeenCalledWith('https://app.test/collections/tok')
		expect(toast.message).toBe('Link copied')
	})

	it('disable link hides copy', () => {
		q.byKey.default = ok(collection({ sharing_enabled: true }))
		const on = render(CollectionEditor, { props: { id: 'c1', onback: () => {} } }).body
		expect(on).toContain('Copy link')
		expect(on).toContain('Disable link')
		expect(on).toContain('Anyone with the link can see this collection')
		q.byKey.default = ok(collection({ sharing_enabled: false }))
		const off = render(CollectionEditor, { props: { id: 'c1', onback: () => {} } }).body
		expect(off).not.toContain('Copy link')
		expect(off).not.toContain('Disable link')
		expect(off).toContain('1 / 50')
	})

	it('remove calls removeItem and invalidates', async () => {
		await removeItem('c1', 'i1')
		expect(crm.collections.removeItem).toHaveBeenCalledWith('c1', 'i1')
		const keys = qc.invalidateQueries.mock.calls.map((c) => c[0].queryKey)
		expect(keys).toContainEqual(crmKeys.collection('c1'))
		expect(keys).toContainEqual(crmKeys.collectionsAll())
	})

	it('empty state copy', () => {
		q.byKey.default = ok({ items: [], total: 0, limit: 50, offset: 0 })
		const html = render(CollectionList, { props: { onopen: () => {} } }).body
		expect(html).toContain('No collections yet — add properties from Company listings.')
	})

	it('menu row state: loading, in collection, full, free', () => {
		const c = { item_count: 3 }
		expect(menuRowState(c, undefined, '111')).toEqual({
			checked: false,
			disabled: true,
			hint: null,
			pending: true
		})
		const detail = { items: [{ listing_key: '111' }] }
		expect(menuRowState(c, detail, '111')).toMatchObject({ checked: true, disabled: true })
		expect(menuRowState(c, detail, '222')).toMatchObject({ checked: false, disabled: false })
		expect(menuRowState({ item_count: 50 }, detail, '222')).toMatchObject({
			disabled: true,
			hint: '50 / 50'
		})
	})

	it('delete leaves first, drops the detail from cache and never refetches it', async () => {
		const order: string[] = []
		qc.removeQueries.mockImplementation(() => order.push('remove'))
		await deleteCollection('c1', () => order.push('back'))
		expect(crm.collections.remove).toHaveBeenCalledWith('c1')
		expect(order).toEqual(['back', 'remove'])
		expect(qc.removeQueries).toHaveBeenCalledWith({ queryKey: crmKeys.collection('c1') })
		const keys = qc.invalidateQueries.mock.calls.map((c) => c[0].queryKey)
		expect(keys).toEqual([crmKeys.collectionsAll()])
	})
})
