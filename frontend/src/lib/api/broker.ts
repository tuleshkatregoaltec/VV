import { client } from './client'
import type { BrokerActionResult, BrokerDocumentResponse } from './generated/hey-api/types.gen'

export type {
	BrokerActionProposal,
	BrokerDocumentDataOutput as BrokerDocumentData,
	BrokerDocumentResponse
} from './generated/hey-api/types.gen'
export type BrokerActionResponse = BrokerActionResult

export const broker = {
	document: (id: string, signal?: AbortSignal) =>
		client.get<BrokerDocumentResponse>(`/api/v1/crm/broker/documents/${encodeURIComponent(id)}`, {
			signal
		}),
	downloadDocument: (id: string, signal?: AbortSignal) =>
		client.get<Blob>(`/api/v1/crm/broker/documents/${encodeURIComponent(id)}/download`, {
			returnBlob: true,
			signal
		}),
	confirmAction: (proposalId: string) =>
		client.post<BrokerActionResponse>('/api/v1/crm/broker/actions/confirm', {
			proposal_id: proposalId
		})
}
