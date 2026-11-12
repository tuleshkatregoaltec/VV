/**
 * Listing documents: labels, and one way to ask for a PDF.
 *
 * The backend decides which details each document needs (it answers 422 `missing_fields`);
 * this file only names them the way the form does.
 */

import { ApiError } from '$lib/api/client'
import type { GeneratedDocumentResponse } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '../../api'
import type { DocType } from '../../api/types'

export const DOC_TYPES: { type: DocType; label: string }[] = [
	{ type: 'noc', label: 'NOC' },
	{ type: 'lease', label: 'Lease Agreement' },
	{ type: 'a2a', label: 'A2A Agreement' }
]

export const docLabel = (type: string): string =>
	DOC_TYPES.find((d) => d.type === type)?.label ?? type

/** Form label for each saved field, by its dotted path. */
export const FIELD_LABELS: Record<string, string> = {
	'listing.title': 'Listing title',
	'listing.area_name': 'Listing area',
	'listing.price_aed': 'Listing price',
	'owner.full_name': 'Owner name',
	'owner.phone': 'Owner phone',
	'owner.email': 'Owner email',
	'owner.title_deed_number': 'Title deed number',
	'owner.id_number': 'Emirates ID / passport number',
	'lease.tenant_name': 'Tenant name',
	'lease.tenant_phone': 'Tenant phone',
	'lease.tenant_email': 'Tenant email',
	'lease.start_date': 'Lease start',
	'lease.end_date': 'Lease end',
	'lease.annual_rent_aed': 'Annual rent (AED)',
	'lease.cheques': 'Number of cheques',
	'lease.security_deposit_aed': 'Security deposit (AED)',
	'a2a.other_brokerage': 'Co-broking brokerage',
	'a2a.other_broker_name': 'Co-broking agent',
	'a2a.other_broker_brn': 'Agent BRN',
	'a2a.commission_split_pct': 'Commission split (%)',
	'a2a.valid_until': 'Agreement valid until'
}

export const fieldLabel = (path: string): string => FIELD_LABELS[path] ?? path

export type GenerateOutcome =
	| { ok: true; document: GeneratedDocumentResponse }
	| { ok: false; kind: 'missing'; fields: string[] }
	| { ok: false; kind: 'stale' }
	| { ok: false; kind: 'failed' }
	| { ok: false; kind: 'error'; error: unknown }

function missingOf(e: ApiError): string[] {
	const detail = (e.details as { detail?: { fields?: unknown } } | undefined)?.detail
	return Array.isArray(detail?.fields) ? detail.fields.map((f) => fieldLabel(String(f))) : []
}

/**
 * Ask for one PDF. One key per click: a dropped connection is retried once with the same key,
 * so the server returns the same document instead of making a second one.
 */
export async function generate(
	listingKey: string,
	docType: DocType,
	revision: number,
	key: string = crypto.randomUUID()
): Promise<GenerateOutcome> {
	const body = {
		source: 'property_finder' as const,
		listing_key: listingKey,
		doc_type: docType,
		expected_revision: revision,
		idempotency_key: key
	}
	for (let attempt = 0; ; attempt++) {
		try {
			return { ok: true, document: await crm.documents.generate(body) }
		} catch (e) {
			if (e instanceof ApiError && e.code === 'network_error' && attempt === 0) continue
			if (e instanceof ApiError) {
				if (e.status === 422 && e.code === 'missing_fields')
					return { ok: false, kind: 'missing', fields: missingOf(e) }
				if (e.status === 409) return { ok: false, kind: 'stale' }
				if (e.status === 502) return { ok: false, kind: 'failed' }
			}
			return { ok: false, kind: 'error', error: e }
		}
	}
}

export type PropertyGroup = {
	listingKey: string
	title: string
	area: string | null
	documents: GeneratedDocumentResponse[]
}
export type CompanyGroup = { company: string; properties: PropertyGroup[] }

/**
 * Company → property → documents. Input is newest first, so groups keep the order of their
 * most recent document and each property's documents stay newest first.
 */
export function groupDocuments(items: GeneratedDocumentResponse[]): CompanyGroup[] {
	const companies = new Map<string, Map<string, PropertyGroup>>()
	for (const doc of items) {
		const company = doc.company_name?.trim() || 'Company not recorded'
		let properties = companies.get(company)
		if (!properties) companies.set(company, (properties = new Map()))
		let property = properties.get(doc.listing_key)
		if (!property) {
			property = {
				listingKey: doc.listing_key,
				title: doc.listing_title,
				area: doc.listing_area ?? null,
				documents: []
			}
			properties.set(doc.listing_key, property)
		}
		property.documents.push(doc)
	}
	return [...companies].map(([company, properties]) => ({
		company,
		properties: [...properties.values()]
	}))
}
