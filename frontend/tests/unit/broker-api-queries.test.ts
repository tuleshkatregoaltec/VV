import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type BrokerDocumentResponse, broker } from '$lib/api/broker'
import { client } from '$lib/api/client'
import { isChatArtifact } from '$lib/chat/artifacts'
import { brokerKeys, brokerQueries } from '$lib/queries/broker'

describe('broker document access and human-confirmed actions', () => {
	beforeEach(() => vi.restoreAllMocks())

	it('downloads through the authenticated client ID route as a blob, never a supplied URL', async () => {
		const pdf = new Blob(['fixture pdf'], { type: 'application/pdf' })
		const get = vi.spyOn(client, 'get').mockResolvedValue(pdf)
		const signal = new AbortController().signal
		await expect(broker.downloadDocument('id/with?delimiters', signal)).resolves.toBe(pdf)
		expect(get).toHaveBeenCalledWith(
			'/api/v1/crm/broker/documents/id%2Fwith%3Fdelimiters/download',
			{ returnBlob: true, signal }
		)
	})

	it('confirms only the stored proposal identifier, without permitting client replacement values', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ status: 'completed' })
		await broker.confirmAction('stored-proposal')
		expect(post).toHaveBeenCalledWith('/api/v1/crm/broker/actions/confirm', {
			proposal_id: 'stored-proposal'
		})
	})

	it('passes cancellation to authorized document reads and does not fetch absent IDs', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({})
		const signal = new AbortController().signal
		const options = brokerQueries.document('document-1')
		expect(options.queryKey).toEqual(brokerKeys.document('document-1'))
		await options.queryFn({ signal })
		expect(get).toHaveBeenCalledWith('/api/v1/crm/broker/documents/document-1', { signal })
		expect(brokerQueries.document(null).enabled).toBe(false)
	})

	it('polls pending jobs and stops on completion, failure or an authorization error', () => {
		const options = brokerQueries.document('document-1')
		for (const status of ['queued', 'running'] as const) {
			expect(
				options.refetchInterval({
					state: { status: 'success', data: { status } as BrokerDocumentResponse }
				})
			).toBe(2000)
		}
		for (const status of ['completed', 'failed'] as const) {
			expect(
				options.refetchInterval({
					state: { status: 'success', data: { status } as BrokerDocumentResponse }
				})
			).toBe(false)
		}
		expect(
			options.refetchInterval({
				state: { status: 'error', data: { status: 'running' } as BrokerDocumentResponse }
			})
		).toBe(false)
		expect(options.retry).toBe(false)
	})

	it('recognizes persisted broker artifacts for chat replay while rejecting unknown types', () => {
		for (const type of ['broker_document', 'broker_action']) {
			expect(
				isChatArtifact({ id: 'artifact-1', type, title: 'Saved broker result', status: 'ready' })
			).toBe(true)
		}
		expect(
			isChatArtifact({ id: 'a', type: 'execute_action', title: 'Unsafe', status: 'ready' })
		).toBe(false)
	})
})
