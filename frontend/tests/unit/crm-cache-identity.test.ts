import { InfiniteQueryObserver } from '@tanstack/svelte-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { client } from '$lib/api/client'
import type { AuthMeResponse, InboundEnquiryResponse } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '$lib/crm/api'
import * as backend from '$lib/crm/api/backend'
import { crmScopeKey } from '$lib/crm/identity.svelte'
import { crmKeys, crmPreviousData, crmQueries } from '$lib/crm/queries'
import { pendingImports, watchQueuedImport } from '$lib/crm/stores/imports.svelte'
import { refreshCrm, write } from '$lib/crm/write'
import { getQueryClient } from '$lib/queries/client'

const users = vi.hoisted(() => ({
	data: null as AuthMeResponse | null,
	listener: (_user: AuthMeResponse | null) => {}
}))
vi.mock('$lib/stores/user.svelte', () => ({
	currentUser: users,
	subscribeUser: (listener: (user: AuthMeResponse | null) => void) => {
		users.listener = listener
		listener(users.data)
		return () => {}
	}
}))
const user = (organization_id = 'org-a', id = 'user-a') =>
	({
		id,
		organization_id,
		email: `${id}@example.test`,
		first_name: id,
		last_name: '',
		role: 'member',
		is_owner: false,
		subscription_status: 'active'
	}) as AuthMeResponse
function identify(value: AuthMeResponse | null) {
	users.data = value
	users.listener(value)
}
const enquiry = {
	id: 7,
	contact: { full_name: 'Buyer', phone: '', registry_profiles: [] },
	intent: 'buy',
	status: 'new',
	source: 'Bayut',
	enquiry_date: '2026-10-31',
	criteria: {},
	tags: [],
	observed_data: {},
	assigned_user_id: 'user-a',
	sla_state: 'on_time',
	review_reasons: [],
	strict_fields: []
} as unknown as InboundEnquiryResponse
beforeEach(() => {
	identify(user())
	getQueryClient().clear()
})
afterEach(() => {
	vi.restoreAllMocks()
	getQueryClient().clear()
	identify(null)
})

describe('private CRM cache identity', () => {
	it('gates private reads before membership is known and separates users within the same org', () => {
		identify(null)
		expect(crmQueries.owners({ tab: 'all' }).enabled).toBe(false)
		identify(user())
		const first = crmKeys.lead(7)
		identify(user('org-a', 'user-b'))
		expect(crmKeys.lead(7)).not.toEqual(first)
	})
	it('removes old org data, rejects old placeholders, and never reuses a fulfilled me response after membership changes', async () => {
		const query = crmQueries.lead(7)
		getQueryClient().setQueryData(query.queryKey, { name: 'Private org A buyer' })
		expect((await backend.me()).name).toBe('user-a')
		identify({ ...user('org-b'), first_name: 'Org B name' })
		expect(crmScopeKey()).toContain('org-b')
		expect(getQueryClient().getQueryData(query.queryKey)).toBeUndefined()
		expect(
			crmPreviousData({ name: 'Private org A buyer' }, { queryKey: query.queryKey })
		).toBeUndefined()
		expect((await backend.me()).name).toBe('Org B name')
	})
	it('cancels an active old-org query so its delayed response cannot refill the cache', async () => {
		const key = crmKeys.lead(7)
		let finish!: (value: string) => void
		const pending = getQueryClient()
			.fetchQuery({
				queryKey: key,
				queryFn: () =>
					new Promise<string>((resolve) => {
						finish = resolve
					})
			})
			.catch(() => null)
		identify(user('org-b'))
		finish('Private org A buyer')
		await pending
		expect(getQueryClient().getQueryData(key)).toBeUndefined()
	})
	it('resets a fulfilled fallback me promise on sign-out before the same user signs in again', async () => {
		identify(null)
		const get = vi.spyOn(client, 'get').mockResolvedValue(user() as never)
		await backend.me()
		identify(user())
		identify(null)
		get.mockResolvedValue({ ...user('org-b'), first_name: 'New membership' } as never)
		expect((await backend.me()).name).toBe('New membership')
		expect(get).toHaveBeenCalledTimes(2)
	})
})

describe('CRM shared reads and explicit matching writes', () => {
	it('shares exact enquiry, import and workspace reads across simultaneous view adapters', async () => {
		const get = vi.spyOn(client, 'get').mockImplementation(async (url) => {
			if (url.includes('/inbound/enquiries/7')) return enquiry
			if (url.includes('/inbound/enquiries')) return { enquiries: [enquiry], total: 1 }
			if (url.includes('/owner-registry')) return { owners: [], total: 0 }
			if (
				url.includes('/owner-workspaces') ||
				url.includes('/contact-imports') ||
				url.includes('/inbound/imports')
			)
				return []
			throw new Error(`Unexpected GET ${url}`)
		})
		await Promise.all([
			backend.listLeads({}),
			backend.matchClients(),
			backend.getLead(7),
			backend.leadEvents(7),
			backend.listImports(),
			backend.listOwnerImports(),
			backend.listOwnerImportDetails(),
			backend.listOwners({ tab: 'all' }),
			backend.listOwners({ tab: 'review' })
		])
		const calls = get.mock.calls.map(([url]) => url.split('?')[0])
		for (const path of [
			'/inbound/enquiries',
			'/inbound/enquiries/7',
			'/contact-imports',
			'/owner-workspaces'
		]) {
			expect(calls.filter((url) => url === `/api/v1/crm${path}`)).toHaveLength(1)
		}
		expect(calls.filter((url) => url.endsWith('/owner-registry'))).toHaveLength(2)
	})
	it('reads valid empty matches without a hidden refresh POST and keeps ignored options out of cache identity', async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url) =>
			url.endsWith('/matches') ? { lanes: {}, updated_at: null } : enquiry
		)
		const post = vi.spyOn(client, 'post').mockResolvedValue({ lanes: {} } as never)
		const result = await backend.leadMatches(7)
		expect(
			result.tiers.every((tier) => tier.groups.every((group) => group.rows.length === 0))
		).toBe(true)
		expect(post).not.toHaveBeenCalled()
		expect(crmKeys.leadMatches(7, { over: true, after: true })).toEqual(
			crmKeys.leadMatches(7, { over: false, after: false })
		)
		await backend.refreshLeadMatches(7)
		expect(post).toHaveBeenCalledExactlyOnceWith('/api/v1/crm/inbound/enquiries/7/matches/refresh')
	})
})

describe('CRM writes refresh visible dependent domains', () => {
	it('lead writes invalidate home/counts/inbox/matches but preserve owner and renewal pages', async () => {
		const keys = [
			crmKeys.lead(7),
			crmKeys.leads({}),
			crmKeys.counts(),
			crmKeys.home('2026-10-31'),
			crmKeys.inbox('all'),
			crmKeys.matchClients(),
			crmKeys.owners({ tab: 'all' }),
			crmKeys.renewal('lease-1')
		]
		for (const key of keys) getQueryClient().setQueryData(key, {})
		await refreshCrm('leads')
		expect(keys.map((key) => getQueryClient().getQueryState(key)?.isInvalidated)).toEqual([
			true,
			true,
			true,
			true,
			true,
			true,
			false,
			false
		])
	})
	it('owner imports invalidate owner evidence, imports and match/feed results, including visible lead counts', async () => {
		const keys = [
			crmKeys.owner('a'),
			crmKeys.ownerHistory('a', {}),
			crmKeys.ownerImportDetails(),
			crmKeys.leadMatches(7),
			crmKeys.feedSummary(),
			crmKeys.counts()
		]
		for (const key of keys) getQueryClient().setQueryData(key, {})
		await refreshCrm('imports')
		expect(keys.every((key) => getQueryClient().getQueryState(key)?.isInvalidated)).toBe(true)
	})
	it('a late write from the previous organization cannot toast, run callbacks or invalidate the new org', async () => {
		let finish!: (value: { data: null }) => void
		const after = vi.fn()
		const pending = write({
			domain: 'leads',
			call: () =>
				new Promise<{ data: null }>((resolve) => {
					finish = resolve
				}),
			after
		})
		identify(user('org-b'))
		const key = crmKeys.counts()
		getQueryClient().setQueryData(key, {})
		finish({ data: null })
		expect(await pending).toBeNull()
		expect(after).not.toHaveBeenCalled()
		expect(getQueryClient().getQueryState(key)?.isInvalidated).toBe(false)
	})
})

describe('renewals load every fixed-size page', () => {
	it('accumulates offset pages past 200 without re-downloading earlier rows and passes cancellation signals', async () => {
		const offsets: number[] = []
		const get = vi.spyOn(client, 'get').mockImplementation(async (url, options) => {
			const params = new URL(url, 'http://test').searchParams
			const offset = Number(params.get('offset'))
			offsets.push(offset)
			expect(params.get('limit')).toBe('50')
			expect(options?.signal).toBeInstanceOf(AbortSignal)
			return {
				leads: Array.from({ length: Math.min(50, 230 - offset) }, (_, i) => ({
					lead_id: String(offset + i),
					days_to_expiry: 1
				})),
				total: 230
			}
		})
		const options = crmQueries.renewalsInfinite({
			area: '',
			window: '',
			property_type: '',
			project: '',
			building: '',
			limit: 50
		})
		const observer = new InfiniteQueryObserver(getQueryClient(), options)
		await observer.refetch()
		while (observer.getCurrentResult().hasNextPage) await observer.fetchNextPage()
		const rows = observer.getCurrentResult().data?.pages.flatMap((page) => page.items)
		expect(rows).toHaveLength(230)
		expect(new Set(rows?.map((row) => row.id)).size).toBe(230)
		expect(offsets).toEqual([0, 50, 100, 150, 200])
		expect(get).toHaveBeenCalledTimes(5)
	})
})

describe('durable import completion belongs to its initiating membership', () => {
	it('completed owner jobs refresh dependent reads without invalidating their own polling data', async () => {
		const options = crmQueries.ownerImportDetails()
		const owner = crmKeys.owners({ tab: 'all' })
		const counts = crmKeys.counts()
		const summary = crmKeys.ownerHistorySummary()
		for (const key of [owner, counts, summary]) getQueryClient().setQueryData(key, {})
		getQueryClient().setQueryData(options.queryKey, [{ id: 91, status: 'retry_wait' }])
		vi.spyOn(crm.imports, 'ownerDetails').mockResolvedValue([
			{ id: 91, status: 'completed' }
		] as never)
		await options.queryFn()
		expect(
			[owner, counts, summary].every((key) => getQueryClient().getQueryState(key)?.isInvalidated)
		).toBe(true)
		expect(getQueryClient().getQueryState(options.queryKey)?.isInvalidated).toBe(false)
	})
	it('a delayed completion poll from a previous organization cannot refresh the new organization', async () => {
		const options = crmQueries.ownerImportDetails()
		getQueryClient().setQueryData(options.queryKey, [{ id: 91, status: 'queued' }])
		let finish!: (jobs: never) => void
		vi.spyOn(crm.imports, 'ownerDetails').mockImplementation(
			() =>
				new Promise((resolve) => {
					finish = resolve
				})
		)
		const poll = options.queryFn()
		identify(user('org-b'))
		const owner = crmKeys.owners({ tab: 'all' })
		const counts = crmKeys.counts()
		for (const key of [owner, counts]) getQueryClient().setQueryData(key, {})
		finish([{ id: 91, status: 'completed' }] as never)
		await poll
		expect(
			[owner, counts].every((key) => !getQueryClient().getQueryState(key)?.isInvalidated)
		).toBe(true)
	})
})

describe('accepted uploads poll only for the current session and identity', () => {
	it('first-read completion refreshes worker-written data and ends its watch even without cached queued history', async () => {
		watchQueuedImport('L91')
		const options = crmQueries.imports()
		const counts = crmKeys.counts()
		getQueryClient().setQueryData(counts, {})
		vi.spyOn(crm.imports, 'list').mockResolvedValue([
			{ id: 'L91', jobStatus: 'completed' }
		] as never)
		await options.queryFn()
		expect(getQueryClient().getQueryState(counts)?.isInvalidated).toBe(true)
		expect(pendingImports.ids).toEqual([])
	})
	it('terminal failures end session polling without claiming that records were imported', async () => {
		watchQueuedImport('L91')
		const options = crmQueries.imports()
		const counts = crmKeys.counts()
		getQueryClient().setQueryData(counts, {})
		vi.spyOn(crm.imports, 'list').mockResolvedValue([{ id: 'L91', jobStatus: 'failed' }] as never)
		await options.queryFn()
		expect(getQueryClient().getQueryState(counts)?.isInvalidated).toBe(false)
		expect(pendingImports.ids).toEqual([])
	})
	it('changing identity clears watches and an old poll cannot end a new-org watch with the same job id', async () => {
		watchQueuedImport('O91')
		const options = crmQueries.imports()
		let finish!: (jobs: never) => void
		vi.spyOn(crm.imports, 'list').mockImplementation(
			() =>
				new Promise((resolve) => {
					finish = resolve
				})
		)
		const poll = options.queryFn()
		identify(user('org-b'))
		expect(pendingImports.ids).toEqual([])
		watchQueuedImport('O91')
		finish([{ id: 'O91', jobStatus: 'completed' }] as never)
		await poll
		expect(pendingImports.ids).toEqual(['O91'])
	})
})
