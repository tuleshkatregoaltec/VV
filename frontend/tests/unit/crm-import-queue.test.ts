import { afterEach, describe, expect, it, vi } from 'vitest'
import { client } from '$lib/api/client'
import type {
	CrmContactImportResponse,
	InboundImportResponse
} from '$lib/api/generated/hey-api/types.gen'
import {
	createImport,
	importOwnerFile,
	listImports,
	listOwnerImportDetails
} from '$lib/crm/api/backend'
import type { ImportStatus, OwnerImportResult } from '$lib/crm/api/types'
import {
	importIsActive,
	importPollInterval,
	importProgressNotice,
	importUploadMessage,
	ownerImportNotice
} from '$lib/crm/importStatus'
import { crmQueries } from '$lib/crm/queries'

const imported = (status: ImportStatus, id = 91): CrmContactImportResponse =>
	({
		id,
		name: 'Synthetic workbook',
		original_filename: 'owners.csv',
		status,
		summary: {},
		mappings: [],
		created_at: '2026-11-01T00:00:00Z'
	}) as CrmContactImportResponse
afterEach(() => vi.restoreAllMocks())

describe('durable import acceptance', () => {
	it.each([
		'queued',
		'retry_wait',
		'processing'
	] as const)('a fresh %s owner job is accepted without reporting imported rows or a duplicate', async (status) => {
		vi.spyOn(client, 'get').mockResolvedValue([])
		vi.spyOn(client, 'post').mockResolvedValue(imported(status))
		const { data } = await importOwnerFile(
			new File(['Name,Unit\nSynthetic,1'], 'owners.csv'),
			'Synthetic workbook'
		)
		expect(data.status).toBe(status)
		expect(data.alreadyImported).toBe(false)
		expect(ownerImportNotice(data)).toBeNull()
		expect(importUploadMessage(data.status, data.summary.candidateRows)).not.toMatch(
			/Imported|0 rows/
		)
		expect(importProgressNotice(data.status)).toMatch(
			/background|resume automatically|Counts appear/
		)
	})
	it('source-only queued results retain their audit mode without implying completed ownership results', async () => {
		const queued = { ...imported('queued'), summary: { source_audit: { mode: 'source_only' } } }
		vi.spyOn(client, 'get').mockResolvedValue([queued])
		const [detail] = await listOwnerImportDetails()
		expect(detail.status).toBe('queued')
		expect(detail.source_audit?.mode).toBe('source_only')
		expect(detail.counts.ownerMatch).toBeNull()
		expect(importUploadMessage(detail.status, detail.counts.kept)).toBe('Import queued')
	})
	it('a reused queued job is not presented as an already completed import', async () => {
		const queued = imported('queued')
		vi.spyOn(client, 'get').mockResolvedValue([queued])
		vi.spyOn(client, 'post').mockResolvedValue(queued)
		const { data } = await importOwnerFile(new File(['Name,Unit\nSynthetic,1'], 'owners.csv'), '')
		expect(data.alreadyImported).toBe(true)
		expect(ownerImportNotice(data)).toContain('already has an import recorded')
		expect(ownerImportNotice(data)).not.toContain('already imported')
		expect(importUploadMessage(data.status, 0, true)).toContain('in progress')
	})
	it('keeps completed replay messaging and row results distinct from queue acceptance', () => {
		const result = {
			...imported('completed'),
			alreadyImported: true
		} as unknown as OwnerImportResult
		expect(ownerImportNotice(result)).toContain('already imported')
		expect(importUploadMessage('completed', 37)).toBe('Imported · 37 rows')
		expect(importUploadMessage('completed', 37, true)).toBeNull()
	})
	it('a queued inbound upload reports Queued with a canonical job status, not Imported', async () => {
		const post = vi
			.spyOn(client, 'post')
			.mockResolvedValue(imported('queued') as unknown as InboundImportResponse)
		const { data } = await createImport(
			new File(['Name,Phone\nSynthetic,0500000000'], 'leads.csv'),
			{
				mode: 'self'
			}
		)
		// Who handles the leads travels with the queued upload; the worker applies it later.
		expect((post.mock.calls[0][1] as FormData).get('assignment_mode')).toBe('self')
		expect(data.jobStatus).toBe('queued')
		expect(data.status).toBe('Queued')
		expect(importUploadMessage(data.jobStatus, data.rows)).toBe('Import queued')
	})
	it('preserves active statuses and hides unfinished row outcomes in mixed and owner history adapters', async () => {
		vi.spyOn(client, 'get').mockImplementation(async (url) =>
			url.includes('/inbound/imports')
				? []
				: [imported('queued', 1), imported('retry_wait', 2), imported('processing', 3)]
		)
		const [mixed, owners] = await Promise.all([listImports(), listOwnerImportDetails()])
		expect(new Set(mixed.map((job) => job.status))).toEqual(
			new Set(['Queued', 'Waiting to retry', 'Processing'])
		)
		expect(owners.map((job) => job.status)).toEqual(['queued', 'retry_wait', 'processing'])
		expect(owners.every((job) => !job.flagged)).toBe(true)
	})
})

describe('durable import polling', () => {
	it('backs off from 5 seconds to a capped minute and stops on terminal states', () => {
		expect([1, 2, 3, 4, 5, 50].map((updates) => importPollInterval(true, updates))).toEqual([
			5000, 10000, 20000, 40000, 60000, 60000
		])
		expect(importPollInterval(false, 50)).toBe(false)
		for (const status of ['completed', 'failed'] as const)
			expect(importIsActive(status)).toBe(false)
	})
	it.each([
		'queued',
		'retry_wait',
		'processing'
	] as const)('owner detail polling continues for %s until completion or failure', (status) => {
		const options = crmQueries.ownerImportDetails()
		const state = (jobStatus: ImportStatus) => ({
			state: { data: [{ id: 91, status: jobStatus }] as never, dataUpdateCount: 1 }
		})
		expect(options.refetchInterval(state(status))).toBe(5000)
		expect(options.refetchInterval(state('completed'))).toBe(false)
		expect(options.refetchInterval(state('failed'))).toBe(false)
	})
	it('the shared mixed import observer polls active inbound jobs and stops without active jobs', () => {
		const options = crmQueries.imports()
		expect(
			options.refetchInterval({
				state: { data: [{ jobStatus: 'retry_wait' }] as never, dataUpdateCount: 3 }
			})
		).toBe(20000)
		expect(
			options.refetchInterval({
				state: {
					data: [{ jobStatus: 'failed' }, { jobStatus: 'completed' }] as never,
					dataUpdateCount: 4
				}
			})
		).toBe(false)
		expect(options.refetchInterval({ state: { data: undefined, dataUpdateCount: 0 } })).toBe(false)
	})
})
