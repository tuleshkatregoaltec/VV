import { render } from 'svelte/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type BrokerActionResponse, type BrokerDocumentResponse, broker } from '$lib/api/broker'
import type { BrokerActionArtifact, BrokerDocumentArtifact } from '$lib/chat/artifacts'
import ChatBrokerArtifact from '$lib/components/chat/ChatBrokerArtifact.svelte'

const queryState = vi.hoisted(() => ({ isError: false }))
vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (options: () => { initialData?: BrokerDocumentResponse }) => ({
		data: options().initialData,
		isError: queryState.isError
	}),
	QueryClient: vi.fn()
}))

function savedDocument(overrides: Partial<BrokerDocumentResponse> = {}): BrokerDocumentResponse {
	return {
		id: 'document-1',
		status: 'completed',
		kind: 'quotation',
		title: 'Client quotation',
		version: 3,
		created_at: '2026-10-03T10:00:00Z',
		error: null,
		download_url: 'https://untrusted.invalid/never-follow',
		document: {
			brand: 'ViteVue',
			title: 'Client quotation',
			reference: 'QUOTE-1',
			version: 3,
			valid_until: '2026-10-17',
			prepared_at: '2026-10-03',
			properties: [],
			sections: [],
			quotation: {
				currency: 'AED',
				lines: [
					{
						label: 'Administration',
						amount: '500.50',
						status: 'estimate',
						basis: 'Explicit estimate'
					},
					{ label: 'Transfer', amount: null, status: 'missing', basis: 'Not supplied' }
				],
				known_total: '1122000.00',
				estimated_total: '500.50',
				total: null,
				missing_charges: ['Transfer']
			},
			limitations: ['Transfer charge is unverified.']
		},
		...overrides
	}
}

function documentArtifact(data = savedDocument()): BrokerDocumentArtifact {
	return {
		id: 'artifact-1',
		type: 'broker_document',
		status: 'ready',
		title: data.title,
		created_at: data.created_at,
		data
	}
}

function actionArtifact(): BrokerActionArtifact {
	const data: BrokerActionResponse = {
		status: 'proposal',
		requires_confirmation: true,
		proposal: {
			proposal_id: 'proposal-1',
			enquiry_id: 12,
			action: 'note',
			scope: 'mine',
			status: 'proposed',
			body: '<script>sendClient()</script>',
			due_date: null,
			expected_updated_at: '2026-10-03T10:00:00Z',
			created_at: '2026-10-03T10:00:00Z'
		}
	}
	return {
		id: 'artifact-2',
		type: 'broker_action',
		status: 'ready',
		title: 'Review note',
		created_at: data.proposal.created_at,
		data
	}
}

describe('broker chat artifact presentation', () => {
	beforeEach(() => {
		queryState.isError = false
		vi.restoreAllMocks()
	})

	it('renders saved decimal strings and incomplete totals without rounding or inventing zero', () => {
		const html = render(ChatBrokerArtifact, { props: { artifact: documentArtifact() } }).body
		expect(html).toContain('1122000.00')
		expect(html).toContain('500.50')
		expect(html).toContain('Not available — charges are missing')
		expect(html).toContain('Download PDF · Version 3')
		expect(html).not.toContain('https://untrusted.invalid')
	})

	it('renders pending and failed states without a successful download or completed preview', () => {
		for (const status of ['queued', 'running', 'failed'] as const) {
			const html = render(ChatBrokerArtifact, {
				props: {
					artifact: documentArtifact(
						savedDocument({ status, error: 'PDF could not be generated.' })
					)
				}
			}).body
			expect(html).not.toContain('Download PDF')
			expect(html).not.toContain('1122000.00')
			if (status === 'failed') expect(html).toContain('PDF could not be generated.')
		}
	})

	it('hides cached private contents after a failed authorization refresh', () => {
		queryState.isError = true
		const html = render(ChatBrokerArtifact, { props: { artifact: documentArtifact() } }).body
		expect(html).toContain('Access may have changed')
		expect(html).not.toContain('1122000.00')
		expect(html).not.toContain('Download PDF')
	})

	it('requires a visible confirmation and escapes proposal text without mutating on render', () => {
		const confirm = vi.spyOn(broker, 'confirmAction')
		const html = render(ChatBrokerArtifact, { props: { artifact: actionArtifact() } }).body
		expect(html).toContain('Confirm action')
		expect(html).toContain('The server checks whether it has already been applied')
		expect(html).toContain('&lt;script>')
		expect(html).not.toContain('<script>sendClient()')
		expect(confirm).not.toHaveBeenCalled()
	})
})
