import { type BrokerDocumentResponse, broker } from '$lib/api/broker'

export const brokerKeys = {
	all: ['crm', 'broker'] as const,
	document: (id: string) => [...brokerKeys.all, 'document', id] as const
}

export const brokerQueries = {
	document: (id: string | null, initialData?: BrokerDocumentResponse) => ({
		queryKey: brokerKeys.document(id ?? ''),
		queryFn: ({ signal }: { signal: AbortSignal }) => broker.document(id ?? '', signal),
		enabled: id !== null,
		initialData,
		staleTime: 0,
		retry: false,
		refetchOnMount: 'always' as const,
		refetchInterval: (query: { state: { data?: BrokerDocumentResponse; status: string } }) =>
			query.state.status !== 'error' &&
			(query.state.data?.status === 'queued' || query.state.data?.status === 'running')
				? 2000
				: false
	})
}
