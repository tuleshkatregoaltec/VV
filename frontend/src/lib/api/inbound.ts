import { client } from './client'

export type InboundIntent = 'buy' | 'rent' | 'sell' | 'let'
export type InboundStatus =
	| 'new'
	| 'needs_review'
	| 'assigned'
	| 'contacted'
	| 'qualified'
	| 'active'
	| 'won'
	| 'nurture'
	| 'closed_lost'
export type InboundMatchState = 'suggested' | 'saved' | 'dismissed' | 'contacted'

export interface InboundContact {
	id: number
	full_name: string
	phone: string | null
	email: string | null
	whatsapp: string | null
	preferred_language: string | null
	preferred_channel: string | null
	consent_status: string
	do_not_contact: boolean
}

export interface InboundNote {
	id: number
	body: string
	user_id: string
	created_at: string
}

export interface InboundEnquiry {
	id: number
	contact: InboundContact
	intent: InboundIntent
	status: InboundStatus
	assigned_user_id: string | null
	source: string
	campaign: string | null
	source_import_id: number | null
	enquiry_date: string
	criteria: Record<string, unknown>
	strict_fields: string[]
	raw_notes: string | null
	extraction_confidence: number
	review_reasons: string[]
	next_follow_up: string | null
	tags: string[]
	notes: InboundNote[]
	match_count: number
	saved_match_count: number
	created_at: string
	updated_at: string
}

export interface InboundEnquiryList {
	enquiries: InboundEnquiry[]
	total: number
	summary: Record<string, number>
}

export interface InboundEnquiryCreate {
	intent: InboundIntent
	full_name: string
	phone?: string
	email?: string
	whatsapp?: string
	source?: string
	campaign?: string
	notes?: string
	criteria: Record<string, unknown>
	strict_fields?: string[]
	consent_status?: string
}

export interface InboundImport {
	id: number
	name: string
	original_filename: string
	status: 'processing' | 'completed' | 'failed'
	summary: {
		total_rows: number
		imported: number
		duplicates: number
		needs_review: number
		buyers: number
		tenants: number
		sellers: number
		landlords: number
	}
	mapping: Record<string, unknown>
	error_message: string | null
	created_at: string
	completed_at: string | null
}

export interface InboundMatch {
	id: number
	target_type: 'owner' | 'unit' | 'listing' | 'demand'
	target_key: string
	score: number
	state: InboundMatchState
	title: string
	subtitle: string
	reasons: string[]
	score_breakdown: Record<string, unknown>
	snapshot: Record<string, unknown>
	generated_at: string
}

export interface InboundMatches {
	enquiry_id: number
	listing_fresh: boolean
	listing_last_refresh: string | null
	lanes: {
		owners: InboundMatch[]
		units: InboundMatch[]
		listings: InboundMatch[]
		demand: InboundMatch[]
	}
}

export const inbound = {
	list: (params: { intent_group?: 'demand' | 'instructions'; status?: string; search?: string } = {}) =>
		client.get<InboundEnquiryList>(client.withQuery('/api/v1/crm/inbound/enquiries', params)),
	get: (id: number) => client.get<InboundEnquiry>(`/api/v1/crm/inbound/enquiries/${id}`),
	create: (payload: InboundEnquiryCreate) =>
		client.post<InboundEnquiry, InboundEnquiryCreate>('/api/v1/crm/inbound/enquiries', payload),
	update: (id: number, payload: Partial<Pick<InboundEnquiry, 'intent' | 'status' | 'assigned_user_id' | 'criteria' | 'strict_fields' | 'next_follow_up' | 'tags'>>) =>
		client.patch<InboundEnquiry, typeof payload>(`/api/v1/crm/inbound/enquiries/${id}`, payload),
	addNote: (id: number, body: string) =>
		client.post<InboundEnquiry, { body: string }>(`/api/v1/crm/inbound/enquiries/${id}/notes`, { body }),
	matches: (id: number) => client.get<InboundMatches>(`/api/v1/crm/inbound/enquiries/${id}/matches`),
	refreshMatches: (id: number, expandUnits = false) => client.post<InboundMatches>(`/api/v1/crm/inbound/enquiries/${id}/matches/refresh?expand_units=${expandUnits}`),
	updateMatch: (id: number, state: InboundMatchState) =>
		client.patch<InboundMatch, { state: InboundMatchState }>(`/api/v1/crm/inbound/matches/${id}`, { state }),
	imports: () => client.get<InboundImport[]>('/api/v1/crm/inbound/imports'),
	upload: (file: File, name: string) => {
		const form = new FormData()
		form.set('file', file)
		form.set('name', name)
		return client.post<InboundImport, FormData>('/api/v1/crm/inbound/imports', form)
	},
	deleteImport: (id: number) => client.delete<void>(`/api/v1/crm/inbound/imports/${id}`)
}
