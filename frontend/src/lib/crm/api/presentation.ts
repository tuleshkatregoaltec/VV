/** Fictional, read-only CRM fixtures. Never persisted or sent to the live backend. */
import { ApiError } from '$lib/api/client'
import { addDays } from '../format'
import { importCounts } from '../ownerImportReport'
import type { CrmApi } from './index'
import type * as T from './types'

const names = [
	'Amira Nasser',
	'Rohan Mehta',
	'Sofia Laurent',
	'Omar Haddad',
	'Maya Bennett',
	'Daniel Rahman',
	'Leila Farouk',
	'Arjun Kapoor',
	'Elena Moreau',
	'Yusuf Mansour',
	'Nadia Sterling',
	'Adam Khalil',
	'Zara Malik',
	'Lucas Beaumont',
	'Hana Qureshi',
	'Karim Soliman',
	'Priya Menon',
	'Oliver Hayes',
	'Sara Darwish',
	'Marco Bellini',
	'Aisha Rafiq',
	'Ethan Clarke',
	'Noor Hamdan',
	'Vikram Sethi'
]
const agents = ['Maya Bennett', 'Omar Haddad', 'Sofia Laurent', 'Rohan Mehta']
// Areas are real places; buildings, people, units and commercial events are fictional.
const locations = [
	['Dubai Marina', 'Marina Crescent', 2450000, 145000],
	['Downtown Dubai', 'Boulevard Heights East', 3400000, 195000],
	['Business Bay', 'Canal Vista Residences', 1950000, 115000],
	['Dubai Hills Estate', 'Parkside Gardens', 4200000, 240000],
	['Palm Jumeirah', 'Azure Shore Residences', 6800000, 340000],
	['Jumeirah Village Circle', 'Orchid Court', 1250000, 82000]
] as const
const saleStages = [
	'Offer accepted',
	'Form F signed',
	'Mortgage / bank',
	'NOC',
	'Transfer booked',
	'Transferred'
]
const rentStages = ['Contract', 'Deposit and cheques', 'Ejari', 'Keys']
const leadTypes: T.LeadType[] = ['buyer', 'seller', 'tenant', 'landlord']
const stages: T.LeadStage[] = [
	'new',
	'contacted',
	'qualified',
	'viewing',
	'offer',
	'won',
	'lost',
	'qualified'
]
const sources: T.Source[] = ['inbound', 'own_contact', 'file', 'agent_to_agent']
const sourceLabels = ['Property Finder', 'Referral', 'Agency owner file', 'Partner agent']
const chip = (label: string, tone: T.Tone = 'neutral'): T.Chip => ({ label, tone })
const amount = (value: number) => `AED ${value.toLocaleString('en-US')}`
const rejectWrite = async () => {
	throw new ApiError(
		'This presentation is read-only. No records were changed or messages sent.',
		405,
		'presentation_read_only'
	)
}

/** Default-deny every operation, including future API additions: never fall back to live writes. */
function blocked<TApi extends object>(api: TApi): TApi {
	return Object.fromEntries(
		Object.entries(api).map(([key, value]) => [
			key,
			typeof value === 'function' ? rejectWrite : blocked(value)
		])
	) as TApi
}

export function createPresentationCrm(live: CrmApi, today: string): CrmApi {
	const base = blocked(live)
	const date = (days: number) => addDays(today, days)
	const stamp = (days: number) => `${date(days)}T09:30:00+04:00`
	const find = <R extends { id: string | number }>(rows: R[], id: string | number): R => {
		const row = rows.find((r) => r.id === id)
		if (!row) throw new ApiError('Record not found in this presentation.', 404, 'not_found')
		return structuredClone(row)
	}
	const leads: T.LeadDetail[] = Array.from({ length: 72 }, (_, i) => {
		const [area, building, sale, rent] = locations[i % locations.length]
		const lead_type = leadTypes[i % 4]
		const deal_type = i % 4 < 2 ? 'sale' : 'rent'
		const seller = lead_type === 'seller' || lead_type === 'landlord'
		const beds = 1 + (i % 4)
		const value = Math.round((deal_type === 'sale' ? sale : rent) * (0.9 + (i % 5) * 0.08))
		const stage = stages[Math.floor(i / 4) % stages.length]
		const name = `${names[i % names.length]}${i >= names.length ? ` ${['Alvi', 'Reed'][Math.floor(i / names.length) - 1]}` : ''}`
		const unit = `${building} #${1201 + i}`
		return {
			id: 900001 + i,
			name,
			phone: '',
			email: `client.${i + 1}@example.com`,
			lead_type,
			deal_type,
			source: sources[Math.floor(i / 4) % 4],
			source_detail: sourceLabels[Math.floor(i / 4) % 4],
			received_label: i < 8 ? 'Today' : `${1 + (i % 14)} days ago`,
			stage: seller && stage === 'viewing' ? 'listed' : stage,
			agent: agents[i % agents.length],
			// Fictional, read-only rows: no real assignee, team or pool behind them.
			assigned_user_id: null,
			assignment_revision: 0,
			team_id: null,
			shared: false,
			score: 98 - (i % 42),
			area,
			language: i % 5 === 0 ? 'Arabic / English' : 'English',
			next_action: [
				'Confirm preferred viewing time',
				'Send two-bedroom shortlist',
				'Review revised offer',
				'Confirm finance pre-approval'
			][i % 4],
			off_plan: lead_type === 'buyer' && i % 12 === 0,
			gated: false,
			owner_id: seller ? `PO-${(i % 24) + 1}` : null,
			fields: {
				wants: `${beds} bedroom apartment`,
				bedrooms: beds,
				budget_aed: value,
				finance: i % 3 ? 'Mortgage pre-approved' : 'Cash',
				purpose: i % 2 ? 'Investment' : 'End use',
				timeline: 'Within 60 days',
				unit,
				building,
				unit_number: String(1201 + i),
				target_price_aed: value,
				expected_rent_aed: rent,
				furnishing: 'Unfurnished',
				move_in: date(30)
			},
			summary: {
				line: seller ? unit : `${beds} bedroom apartment in ${area}`,
				sub: `${amount(value)}${deal_type === 'rent' ? ' / year' : ''} · ${i % 3 ? 'Finance ready' : 'Cash buyer'}`
			},
			known: i % 3 ? 'Ownership on file' : 'Previous enquiry on file',
			source_short: sourceLabels[Math.floor(i / 4) % 4],
			listing: null,
			lease: null,
			recent_sales: null,
			owner_match: {
				summary: i % 3 ? 'Ownership on file' : 'Previous enquiry on file',
				records: []
			},
			pursued: [],
			suggested_agent: null,
			listing_card: null,
			own_listing: null,
			deal: null,
			stage_documents: [],
			can_undo: false
		}
	})
	const listings: T.ListingDetail[] = Array.from({ length: 30 }, (_, i) => {
		const [area, building, sale, rent] = locations[i % 6]
		const lead = leads[i * 2 + 1]
		const deal_type = Math.floor(i / 6) % 2 === 0 ? 'rent' : 'sale'
		const status = i % 10 === 9 ? 'expired' : i % 5 === 4 ? 'pocket' : 'live'
		return {
			id: `PL-${i + 1}`,
			unit: `${building} #${1201 + i * 2 + 1}`,
			area,
			bedrooms: 1 + (i % 4),
			size_sqft: 780 + (i % 6) * 260,
			price_aed: deal_type === 'sale' ? sale : rent,
			deal_type,
			status,
			scope: i % 3 ? 'company' : 'mine',
			agent: agents[i % 4],
			owner: lead.name,
			portals: status === 'live' ? 'Property Finder · Bayut' : 'Private inventory',
			days_live: 3 + i * 2,
			enquiries: 2 + (i % 13),
			permit: null,
			permit_chip: chip('On file', 'green'),
			form_a_expires: date(12 + i),
			form_a_chip: chip('Signed', 'green'),
			comparables_note: 'Pricing reviewed with the owner',
			from_lead_id: lead.id,
			documents: { required: ['Title deed', 'Form A'], notes: {}, received: [] },
			form_a_status: chip('Signed', 'green'),
			permit_status: 'none',
			leads: [lead],
			lead_stages: null,
			deals: [],
			matched: leads
				.filter((l) => l.area === area && ['buyer', 'tenant'].includes(l.lead_type))
				.slice(0, 3),
			from_lead: { id: lead.id, name: lead.name, lead_type: lead.lead_type },
			can_publish: false
		}
	})
	const deals: T.DealDetail[] = Array.from({ length: 18 }, (_, i) => {
		const listing = listings[i]
		const lead = leads[((i * 4) % leads.length) + (listing.deal_type === 'rent' ? 2 : 0)]
		const rent = listing.deal_type === 'rent'
		const sequence = rent ? rentStages : saleStages
		const closed = i >= 14
		const stage_index = closed ? sequence.length - 1 : i % (sequence.length - 1)
		const rate = rent ? 5 : 2
		const gross = (listing.price_aed * rate) / 100
		const net = gross * 0.9
		const missing = i % 3 === 0 ? ['Bank clearance letter'] : []
		const id = `PD-${1001 + i}`
		const result: T.DealDetail = {
			id,
			deal_type: listing.deal_type,
			unit: listing.unit,
			client: lead.name,
			counterparty: listing.owner,
			value_aed: listing.price_aed,
			agent: listing.agent,
			lead_id: lead.id,
			listing_id: listing.id,
			due_date: date(closed ? -i : i + 2),
			next_step: closed ? 'Client handover completed' : sequence[stage_index + 1],
			approval: 'approved',
			dld_transaction_id: null,
			stages: sequence,
			stage_index,
			stage: sequence[stage_index],
			next_stage: closed ? null : sequence[stage_index + 1],
			closed,
			docs_received: 4 - missing.length,
			docs_required: 4,
			missing,
			due_chip: chip(closed ? 'Completed' : `In ${i + 2} days`, closed ? 'green' : 'blue'),
			commission: {
				rate_pct: rate,
				cobroker_pct: 10,
				referral_pct: 0,
				agent_pct: 50,
				invoice_status: closed ? 'received' : i % 3 ? 'due' : 'not_invoiced',
				cobroker_name: 'Harbour Lane Realty',
				referral_name: null,
				amounts: {
					gross,
					cobroker: gross * 0.1,
					referral: 0,
					net,
					agent: net / 2,
					agency: net / 2,
					vat: gross * 0.05
				}
			},
			documents: {
				required: [
					'Signed agreement',
					'Identity documents',
					'Payment schedule',
					'Bank clearance letter'
				],
				received: []
			},
			compliance: {
				due_diligence: 'pending',
				screening: 'not_run',
				cash_aed: 0,
				goaml_required: false
			},
			listing: { id: listing.id, label: listing.unit },
			lead: { id: String(lead.id), label: lead.name },
			forms: [],
			checklist: sequence.map((name, index) => ({
				index,
				name,
				who: index < 2 ? 'Agent and client' : 'Conveyancing team',
				state: index < stage_index ? 'done' : index === stage_index ? 'now' : 'next',
				chip: chip(
					index < stage_index ? 'Complete' : index === stage_index ? 'In progress' : 'Upcoming',
					index < stage_index ? 'green' : 'neutral'
				),
				items: [
					{ key: `${id}-${index}`, label: name, doc: null, done: index < stage_index, file: null }
				]
			}))
		}
		// Document metadata is illustrative; no downloadable identity documents are created.
		result.documents.received = result.documents.required
			.filter((type) => !missing.includes(type))
			.map((type, index) => ({
				id: 970000 + i * 10 + index,
				type,
				file: `${id}-${type.toLowerCase().replaceAll(' ', '-')}.pdf`,
				size_bytes: 148000 + index * 24000,
				uploaded: date(-3)
			}))
		result.docs_received = result.documents.received.length
		listing.deals.push({ id, client: lead.name, stage: result.stage })
		lead.deal = { id, label: listing.unit, stage: result.stage }
		return result
	})
	const owners: T.OwnerDetail[] = Array.from({ length: 24 }, (_, i) => {
		const owned = listings.filter((_, j) => j % 24 === i)
		const name = leads[i * 2 + 1].name
		const unit_rows: T.OwnerUnit[] = owned.map((l, j) => ({
			key: l.id,
			id: l.id,
			number: l.unit.split('#')[1],
			building: l.unit.split(' #')[0],
			area: l.area,
			type: 'Apartment',
			bedrooms: l.bedrooms,
			size_sqft: l.size_sqft,
			bought_aed: Math.round(locations[i % 6][2] * 0.78),
			bought_year: 2022,
			owned_from: '2022-05-18',
			owned_to: null,
			status: 'verified_current_owner',
			status_chip: chip('Ownership on file', 'green'),
			rent: { aed: locations[i % 6][3], from: date(-320 + i), to: date(45 + i) },
			market: {
				sale: [locations[i % 6][2] * 0.95, locations[i % 6][2] * 1.05],
				estimate: locations[i % 6][2],
				confidence: 'medium' as const,
				valued_at: date(0),
				rent: [locations[i % 6][3] * 0.95, locations[i % 6][3] * 1.05]
			},
			rent_history: [
				{ year: 2024, aed: locations[i % 6][3] * 0.85 },
				{ year: 2025, aed: locations[i % 6][3] * 0.92 }
			],
			transactions: [
				{ when: '18 May 2022', what: 'Purchase', aed: Math.round(locations[i % 6][2] * 0.78) }
			],
			source: `Agency portfolio · Row ${i + j + 1}`
		}))
		return {
			id: `PO-${i + 1}`,
			name,
			sources: ['agency_import'],
			source_label: 'Agency portfolio',
			units: owned.map((l) => l.unit),
			units_total: owned.length,
			units_current: owned.length,
			developer_side_seller: false,
			next_event: i % 2 ? 'Lease renewal review' : 'Portfolio review',
			next_event_date: date(7 + i),
			next_event_label: `In ${7 + i} days`,
			last_contact: date(-i % 10),
			tag: i % 3 ? 'Investor' : 'Portfolio client',
			market_update_due: i % 4 === 0,
			mine: i % 3 === 0,
			on_file: true,
			prior_deal: true,
			lead: { id: leads[i * 2 + 1].id, stage: leads[i * 2 + 1].stage, agent: agents[i % 4] },
			phone_numbers: [],
			unit_rows,
			imported_from: [],
			matched: leads.filter((l) => l.area === owned[0]?.area).slice(0, 3),
			notes: [
				{
					id: i + 1,
					at: stamp(-2),
					text: 'Prefers a concise monthly portfolio review. Discuss renewal options six weeks before expiry.',
					origin: 'human'
				}
			],
			relationship: [
				{
					kind: 'Listing agreement',
					transaction: true,
					text: 'Agency representation agreement on file',
					date: date(-90),
					ref: owned[0] ? { kind: 'listing', id: owned[0].id } : null,
					added: false
				}
			],
			create_lead: null
		}
	})
	// Consistent links: listings and seller leads point to their actual fixture owner.
	listings.forEach((l, i) => {
		const owner = owners[i % owners.length]
		l.owner = owner.name
		const lead = leads.find((row) => row.id === l.from_lead_id)
		if (lead) {
			lead.owner_id = owner.id
			lead.own_listing = { id: l.id, label: l.unit, status: l.status }
			lead.owner_match.records = [
				{
					unit: l.unit,
					area: l.area,
					status: 'Ownership on file',
					purchase: '2022',
					owner_id: owner.id,
					owner_name: owner.name
				}
			]
		}
	})
	const events: T.CalendarEvent[] = Array.from({ length: 28 }, (_, i) => {
		const lead = leads[i]
		const listing = listings[i % listings.length]
		const day = (i % 10) - 2
		return {
			id: 910001 + i,
			date: date(day),
			time: `${10 + (i % 8)}:00`,
			kind: i % 3 === 0 ? 'call' : i % 3 === 1 ? 'viewing' : 'follow_up',
			title: i % 3 === 1 ? `Viewing · ${listing.unit}` : `Follow up · ${lead.name}`,
			detail: `${lead.name} · ${lead.area}`,
			agent: lead.agent ?? agents[0],
			lead_id: lead.id,
			deal_id: null,
			listing_id: listing.id,
			owner_id: null,
			context: `${lead.lead_type} · ${lead.source_short}`,
			record: { kind: 'lead', id: String(lead.id), label: lead.name },
			outcome: day < 0 && i % 2 ? 'Shortlist confirmed; next viewing arranged' : null,
			end_date: date(day),
			end_time: `${11 + (i % 8)}:00`,
			all_day: false,
			repeat: 'none',
			meet: false,
			meet_link: null,
			location: '',
			reminders: [30],
			reminders_use_default: false,
			guests: [],
			guests_can_modify: false,
			guests_can_invite_others: true,
			guests_can_see_other_guests: true,
			show_as: 'busy',
			visibility: 'default',
			rescheduled_from: [],
			google_sync_status: 'local',
			can_edit: true,
			redacted: false
		}
	})
	const renewals: T.RenewalDetail[] = listings.slice(0, 18).map((l, i) => ({
		id: `PR-${i + 1}`,
		unit: l.unit,
		area: l.area,
		property: `${l.bedrooms} bed apartment · ${l.size_sqft} sq ft`,
		rent_aed: locations[i % 6][3],
		lease_start: date(-365 + i * 5 - 20),
		lease_end: date(i * 5 - 20),
		days_left: i * 5 - 20,
		end_chip: chip(i < 4 ? 'Recently expired' : `In ${i * 5 - 20} days`, i < 4 ? 'amber' : 'blue'),
		owner: {
			name: l.owner,
			phone: null,
			email: `owner.${i + 1}@example.com`,
			source: 'Agency portfolio'
		},
		owner_evidence: [],
		reason: 'Lease approaching renewal window',
		action: 'Discuss renewal preferences with the owner',
		last_purchase: { date: '2022-05-18', price_aed: locations[i % 6][2] * 0.78 },
		gross_yield_pct: 5.9,
		history: [
			{
				id: `PH-${i}`,
				kind: 'lease',
				date: date(-365 + i * 5 - 20),
				end_date: date(i * 5 - 20),
				title: 'Annual tenancy',
				detail: 'Annual tenancy agreement',
				amount_aed: locations[i % 6][3],
				source: 'Agency file'
			}
		],
		match_explanation: 'Building and unit match the agency portfolio'
	}))
	const connections: T.Connection[] = [
		{
			id: 'portal',
			name: 'Property Finder',
			detail: 'Portal enquiries',
			status: 'Sample feed',
			tone: 'blue',
			kind: 'source'
		},
		{
			id: 'agency',
			name: 'Agency portfolio',
			detail: 'Owner and property records',
			status: 'On file',
			tone: 'green',
			kind: 'import'
		}
	]
	const inbox: T.InboxItem[] = leads.slice(0, 16).map((l, i) => ({
		id: `PI-${i + 1}`,
		name: l.name,
		source: l.source_short,
		line: 'in',
		at_label: `Today · ${9 + (i % 8)}:15`,
		ago: `${5 + i * 7} min ago`,
		text: `Interested in a ${l.fields.bedrooms}-bedroom apartment in ${l.area}. Budget ${amount(Number(l.fields.budget_aed))}. Available for a viewing this week.`,
		owner_check: l.known,
		priority: i < 5 ? 'High intent' : 'New enquiry',
		state: i < 6 ? 'waiting' : 'assigned',
		status_chip: chip(i < 6 ? 'Waiting for a manager' : 'Assigned', i < 6 ? 'amber' : 'green'),
		agent: i < 6 ? '' : (l.agent ?? ''),
		suggested: l.agent ?? '',
		reason: 'Area experience and current capacity',
		requests: [],
		want_line: l.summary.line,
		lead_id: i < 6 ? null : l.id,
		conversation: [],
		can: {
			ask: false,
			withdraw: false,
			release: false,
			dismiss: false,
			restore: false,
			approve: false,
			// Presentation mode is read only.
			qualify: false
		},
		my_request: null
	}))
	const active = leads.filter((l) => l.stage !== 'lost')
	const leadCounts: T.LeadListResponse['counts'] = {
		all: active.length,
		lost: leads.length - active.length,
		buyer: 0,
		seller: 0,
		tenant: 0,
		landlord: 0,
		owner: 0
	}
	for (const lead of active) leadCounts[lead.lead_type]++
	const newLeads = active.filter((l) => l.stage === 'new')
	const openDeals = deals.filter((d) => !d.closed)
	const totals = deals.reduce(
		(a, d) => ({
			gross: a.gross + d.commission.amounts.gross,
			agent: a.agent + d.commission.amounts.agent,
			agency: a.agency + d.commission.amounts.agency
		}),
		{ gross: 0, agent: 0, agency: 0 }
	)
	const listingCounts = {
		live: listings.filter((l) => l.status === 'live').length,
		pocket: listings.filter((l) => l.status === 'pocket').length,
		expired: listings.filter((l) => l.status === 'expired').length
	}
	const historySummary: T.OwnerHistorySummary = {
		source_event_count: 30,
		identifiable_property_count: 30,
		owner_property_count: 30,
		verified_current_count: 30,
		probable_current_count: 0,
		former_count: 0,
		unresolved_count: 0,
		invalid_identity_source_count: 0,
		legacy_source_event_count: 0,
		resolver_versions: {},
		checked_at: stamp(-1)
	}
	const importRows: T.OwnerImportRow[] = owners.flatMap((o) =>
		o.unit_rows.map((u, i) => ({
			id: Number(o.id.split('-')[1]) * 100 + i,
			ownerKey: o.id,
			name: o.name,
			phone: '',
			building: u.building,
			area: u.area,
			project: u.building,
			propertyType: u.type,
			propertyDetails: {},
			latestSaleDate: u.owned_from,
			latestSalePrice: u.bought_aed,
			unit: u.number,
			date: u.owned_from,
			price: u.bought_aed,
			status: 'verified_current_owner',
			confidence: 0.97,
			reason: 'Building and unit matched to portfolio record',
			sheet: 'Portfolio',
			rowNumber: Number(o.id.split('-')[1]) + i,
			matchOutcome: 'matched_sale',
			matchColour: 'green',
			matchReasons: ['Building, unit, purchase date and price agree'],
			matchedSale: {
				unit: u.number,
				building: u.building,
				project: u.building,
				area: u.area,
				amount_aed: u.bought_aed,
				date: u.owned_from ?? '',
				sqft: u.size_sqft,
				source: 'presentation'
			}
		}))
	)
	const importAreas = [null, ...locations.slice(0, 5).map((location) => location[0])]
	const ownerFiles: T.OwnerImportDetail[] = importAreas.map((area, index) => {
		const rows = importRows.filter((row) => !area || row.area === area)
		const slug = area?.toLowerCase().replaceAll(' ', '-')
		return {
			id: index === 0 ? 950001 : 950009 + index,
			name: area ? `${area} · owner portfolio` : 'Residential portfolio',
			file: area ? `${slug}-owners.csv` : 'residential-portfolio.xlsx',
			status: 'completed',
			at: date(-8 + index),
			createdAt: stamp(-8 + index),
			listId: index === 0 ? 950001 : 950009 + index,
			counts: importCounts({
				total_rows: rows.length,
				candidate_rows: rows.length,
				distinct_properties: rows.length,
				verified_current_owners: rows.length,
				properties_linked_rows: rows.length,
				owner_match: {
					version: 'presentation-v1',
					rows: { matched_sale: rows.length },
					units: {
						total: rows.length,
						confirmed: rows.length,
						review: 0,
						property_only: 0,
						not_matched: 0
					},
					rows_without_unit: 0,
					sales_matched: { transactions: 0, registry: rows.length, total: rows.length }
				}
			}),
			sheets: [
				{
					name: 'Portfolio',
					rows: rows.length,
					family: 'contact_list',
					source: 'heuristic',
					confidence: 0.97,
					fields: [
						{ field: 'contact_name', column: 'Owner' },
						{ field: 'area_name', column: 'Area' },
						{ field: 'building_name', column: 'Building' },
						{ field: 'unit_number', column: 'Unit' },
						{ field: 'property_type', column: 'Property type' },
						{ field: 'transaction_date', column: 'Purchase date' },
						{ field: 'transaction_price_aed', column: 'Purchase price AED' }
					],
					warnings: [],
					checks: []
				}
			],
			flagged: false
		}
	})
	const rowsForImport = (id: number): T.OwnerImportRow[] => {
		const file = find(ownerFiles, id)
		const area = importAreas[ownerFiles.findIndex((item) => item.id === file.id)]
		return importRows
			.filter((row) => !area || row.area === area)
			.map((row, index) => ({ ...row, rowNumber: index + 2 }))
	}
	for (const owner of owners) {
		owner.imported_from = ownerFiles.flatMap((file) => {
			const units = rowsForImport(file.id).filter((row) => row.ownerKey === owner.id).length
			return units
				? [{ importId: file.id, name: file.name, file: file.file, date: file.at, units }]
				: []
		})
	}
	historySummary.source_event_count = ownerFiles.reduce(
		(total, file) => total + file.counts.rows,
		0
	)
	const notifications: T.Notification[] = [
		{
			id: 1,
			text: 'New buyer enquiry',
			detail: `${leads[0].name} · ${leads[0].area}`,
			unread: true,
			ref: { kind: 'lead', id: String(leads[0].id) }
		},
		{
			id: 2,
			text: 'Transfer preparation due',
			detail: deals[3].unit,
			unread: true,
			ref: { kind: 'deal', id: deals[3].id }
		},
		{
			id: 3,
			text: 'Owner portfolio review',
			detail: owners[1].name,
			unread: false,
			ref: { kind: 'owner', id: owners[1].id }
		}
	]
	const listLeads = async (p: T.LeadListParams): Promise<T.LeadListResponse> => {
		const items = leads.filter(
			(l) =>
				(p.lost ? l.stage === 'lost' : l.stage !== 'lost') &&
				(!p.lead_type || l.lead_type === p.lead_type) &&
				(!p.stage || l.stage === p.stage) &&
				(!p.source || l.source === p.source) &&
				(!p.area || l.area === p.area) &&
				(!p.q ||
					`${l.name} ${l.area} ${l.summary.line}`.toLowerCase().includes(p.q.toLowerCase())) &&
				(!p.beds || String(l.fields.bedrooms) === p.beds) &&
				(!p.ptype || p.ptype === 'apartment') &&
				(!p.budget ||
					(p.budget === 's1'
						? Number(l.fields.budget_aed) < 2000000
						: p.budget === 's2'
							? Number(l.fields.budget_aed) >= 2000000 && Number(l.fields.budget_aed) <= 5000000
							: p.budget === 's3'
								? Number(l.fields.budget_aed) > 5000000
								: p.budget === 'r1'
									? Number(l.fields.budget_aed) <= 150000
									: Number(l.fields.budget_aed) > 150000))
		)
		return structuredClone({
			items,
			total: items.length,
			counts: leadCounts,
			new_count: newLeads.length,
			areas: locations.map((l) => l[0])
		})
	}
	const matches = async (id: number): Promise<T.LeadMatches> => {
		const lead = find(leads, id)
		const rows: T.MatchRow[] = listings
			.filter(
				(l) =>
					l.area === lead.area &&
					l.deal_type === lead.deal_type &&
					l.price_aed <= Number(lead.fields.budget_aed)
			)
			.slice(0, 3)
			.map((l) => ({
				key: l.id,
				kind: 'listing',
				title: l.unit,
				sub: `${l.bedrooms} beds · ${amount(l.price_aed)}`,
				line: 'own',
				over_budget: null,
				chip: chip('Matches the brief', 'green'),
				why: ['Preferred area', 'Within the requested price range'],
				ref: { kind: 'listing', id: l.id },
				lead_stages: null,
				colleague: null,
				owner: null,
				pursuable: false,
				pursued: null,
				shortlisted: false,
				watching: false,
				renewal_planned: false,
				after_move: false,
				can_book: false
			}))
		return {
			tab: lead.off_plan
				? 'offplan'
				: ['seller', 'landlord'].includes(lead.lead_type)
					? 'sell'
					: 'ready',
			lead,
			brief: [
				{ k: 'Area', v: lead.area },
				{ k: 'Budget', v: amount(Number(lead.fields.budget_aed)) }
			],
			move_by: date(30),
			shortlist: 0,
			tiers: [
				{
					id: 'agency',
					n: 1,
					title: 'Agency inventory',
					sub: 'Properties matching the client brief',
					chip: chip(`${rows.length} matches`, 'green'),
					gate: null,
					groups: [{ label: null, rows, empty: 'No matching inventory' }],
					hidden_after: 0
				}
			],
			status: null,
			own_listing: lead.own_listing,
			needs_brief: false
		}
	}
	return {
		...base,
		me: async () => ({
			name: agents[0],
			initials: 'MB',
			role: 'agent',
			is_owner: true,
			today,
			areas: locations.map((l) => l[0])
		}),
		counts: async () => ({
			new_leads: newLeads.length,
			inbox: inbox.length,
			open_deals: openDeals.length,
			events_today: events.filter((e) => e.date === today).length,
			waiting: 6,
			unread_notifications: 2
		}),
		home: async (day): Promise<T.HomeResponse> => {
			const selected = day || today
			const monday = addDays(selected, -((new Date(`${selected}T00:00:00Z`).getUTCDay() + 6) % 7))
			return structuredClone({
				date: selected,
				facts: {
					events_today: events.filter((e) => e.date === selected).length,
					conveyancing: openDeals.length,
					permits_under_14: 2
				},
				counters: {
					viewings_week: {
						count: events.filter(
							(e) => e.kind === 'viewing' && e.date >= monday && e.date <= addDays(monday, 6)
						).length,
						next: 'Today · 14:00'
					},
					expiring_14: { count: 3, permits: 2, form_a: 1 },
					market: { area: 'Dubai Marina', psf_aed: 2180, rent_median_aed: 145000, yield_pct: 5.9 },
					commission: {
						received_aed: deals
							.filter((d) => d.closed)
							.reduce((n, d) => n + d.commission.amounts.agent, 0),
						due_aed: openDeals.reduce((n, d) => n + d.commission.amounts.agent, 0)
					},
					new_leads: newLeads.length,
					overdue: 2,
					conveyancing: {
						count: openDeals.length,
						value_aed: openDeals.reduce((n, d) => n + d.value_aed, 0)
					}
				},
				week: Array.from({ length: 7 }, (_, i) => ({
					date: addDays(monday, i),
					kinds: events.filter((e) => e.date === addDays(monday, i)).map((e) => e.kind)
				})),
				day: events.filter((e) => e.date === selected),
				conveyancing: openDeals,
				new_leads: newLeads,
				gaps: [
					{
						text: 'Finance approval due',
						detail: leads[2].name,
						ref_type: 'lead',
						ref_id: String(leads[2].id)
					}
				],
				file_leads: active.filter((l) => l.source === 'file').slice(0, 5)
			})
		},
		leads: {
			...base.leads,
			list: listLeads,
			get: async (id) => find(leads, id),
			events: async (id) => [
				{
					id,
					at: stamp(-1),
					text: `Discussed preferences with ${find(leads, id).name}; shortlist to follow.`,
					origin: 'human',
					revertible: false
				}
			],
			matches,
			conversation: async () => []
		},
		feed: {
			...base.feed,
			summary: async () => ({
				areas: locations.map((l) => l[0]),
				forward_days: 90,
				lookback_days: 60,
				window_total: renewals.length,
				on_file: renewals.length,
				entered_today: 3
			}),
			areas: async () =>
				locations.map((l) => ({
					area: l[0],
					owners_in_90_day_window: renewals.filter((r) => r.area === l[0]).length
				})),
			preferences: async () => ({
				areas: locations.map((l) => l[0]),
				forward_days: 90,
				lookback_days: 60
			})
		},
		inbox: {
			...base.inbox,
			list: async (filter) => {
				const lists = {
					all: inbox,
					mine: inbox.filter((i) => i.state === 'assigned'),
					waiting: inbox.filter((i) => i.state === 'waiting')
				}
				return structuredClone({
					items: lists[filter],
					lists,
					counts: { all: lists.all.length, mine: lists.mine.length, waiting: lists.waiting.length },
					today: inbox.length,
					waiting: lists.waiting.length,
					handout: 'manager',
					handout_label: 'Manager assigns',
					sources: connections
				})
			}
		},
		settings: {
			...base.settings,
			handout: async () => ({
				mode: 'manager',
				options: [
					{
						id: 'manager',
						label: 'Manager assigns',
						line: 'Distribute enquiries by expertise and availability'
					},
					{ id: 'request', label: 'First to ask', line: 'Agents request available enquiries' },
					{ id: 'both', label: 'Request and approve', line: 'Agents request; a manager confirms' }
				],
				log: [
					{
						id: 1,
						at: date(-3),
						who: agents[0],
						from: 'both',
						to: 'manager',
						from_label: 'Request and approve',
						to_label: 'Manager assigns'
					}
				],
				stages: [
					{
						types: 'Buyers and tenants',
						stages: ['New', 'Contacted', 'Qualified', 'Viewing', 'Offer', 'Won'],
						proposal: false
					},
					{
						types: 'Sellers and landlords',
						stages: ['New', 'Contacted', 'Qualified', 'Listed', 'Offer', 'Won'],
						proposal: false
					}
				]
			})
		},
		matches: {
			...base.matches,
			clients: async () => {
				const row = (l: T.LeadRow) => ({ lead: l, line: l.summary.line, pursued: 0 })
				return structuredClone({
					ready: active
						.filter((l) => ['buyer', 'tenant'].includes(l.lead_type) && !l.off_plan)
						.map(row),
					offplan: active.filter((l) => l.off_plan).map(row),
					sell: active.filter((l) => ['seller', 'landlord'].includes(l.lead_type)).map(row)
				})
			}
		},
		deals: {
			...base.deals,
			stages: async () => ({ sale: saleStages, rent: rentStages }),
			get: async (id) => find(deals, id),
			list: async (tab, type) =>
				structuredClone({
					items: deals.filter(
						(d) =>
							(!type || d.deal_type === type) &&
							(tab === 'closed'
								? d.closed
								: tab === 'missing_documents'
									? !d.closed && d.missing.length > 0
									: tab === 'commission'
										? true
										: !d.closed)
					),
					counts: {
						open: openDeals.length,
						missing_documents: openDeals.filter((d) => d.missing.length).length,
						closed: deals.length - openDeals.length,
						sale: openDeals.filter((d) => d.deal_type === 'sale').length,
						rent: openDeals.filter((d) => d.deal_type === 'rent').length
					},
					open_value_aed: openDeals.reduce((n, d) => n + d.value_aed, 0),
					totals
				})
		},
		listings: {
			...base.listings,
			get: async (id) => find(listings, id),
			list: async (scope, status, limit = 100, offset = 0, filter) => {
				const found = listings.filter(
					(l) =>
						(scope === 'company' || l.scope === 'mine') &&
						(!status || l.status === status) &&
						(!filter?.search ||
							`${l.unit} ${l.area}`.toLowerCase().includes(filter.search.toLowerCase())) &&
						(!filter?.agentName || l.agent === filter.agentName)
				)
				return structuredClone({
					items: found.slice(offset, offset + limit),
					counts: listingCounts,
					total: found.length,
					limit,
					offset,
					companies: [],
					agent_inventory: agents.map((agent_name) => ({
						agent_id: null,
						agent_name,
						listings: listings.filter((l) => l.agent === agent_name).length
					}))
				})
			}
		},
		portfolio: {
			...base.portfolio,
			get: async () => {
				const closed = deals.filter((d) => d.closed)
				return {
					clients: closed.map((d) => ({
						client: d.client,
						transactions: [
							{
								what: d.deal_type === 'sale' ? 'Sale completed' : 'Tenancy completed',
								kind: d.deal_type,
								unit: d.unit,
								value_aed: d.value_aed,
								date: d.due_date,
								dld_or_ejari: '',
								commission_aed: d.commission.amounts.agent
							}
						]
					})),
					totals: {
						sales: closed.filter((d) => d.deal_type === 'sale').length,
						sales_value_aed: closed
							.filter((d) => d.deal_type === 'sale')
							.reduce((n, d) => n + d.value_aed, 0),
						lets: closed.filter((d) => d.deal_type === 'rent').length,
						lets_value_aed: closed
							.filter((d) => d.deal_type === 'rent')
							.reduce((n, d) => n + d.value_aed, 0),
						commission_aed: closed.reduce((n, d) => n + d.commission.amounts.agent, 0),
						clients: closed.length
					}
				}
			}
		},
		renewals: {
			...base.renewals,
			get: async (id) => find(renewals, id),
			list: async (p) => {
				const found = renewals.filter(
					(r) =>
						(!p.area || r.area === p.area) &&
						(!p.window ||
							(['vacant', 'expired'].includes(p.window)
								? r.days_left < 0
								: r.days_left >= 0 && r.days_left <= Number(p.window.split('_')[1]))) &&
						(!p.building || r.unit.startsWith(p.building))
				)
				return structuredClone({
					offset: p.offset ?? 0,
					items: found.slice(p.offset ?? 0, (p.offset ?? 0) + p.limit),
					total: found.length,
					property_types: ['Apartment'],
					projects: [],
					buildings: [...new Set(found.map((r) => r.unit.split(' #')[0]))]
				})
			}
		},
		market: {
			...base.market,
			list: async () =>
				listings.map((l) => ({
					id: l.id,
					unit: l.unit,
					area: l.area,
					deal_type: l.deal_type,
					price_aed: l.price_aed,
					value_from_comparables_aed: l.price_aed * 1.04,
					discount_pct: 4,
					discount_chip: chip('4% below comparison', 'green'),
					portal: 'Agency inventory',
					days_listed: l.days_live,
					price_cuts: 1,
					watch: false
				})),
			get: async (id) => {
				const l = find(listings, id)
				return {
					id: l.id,
					unit: l.unit,
					area: l.area,
					deal_type: l.deal_type,
					price_aed: l.price_aed,
					value_from_comparables_aed: l.price_aed * 1.04,
					discount_pct: 4,
					discount_chip: chip('4% below comparison', 'green'),
					portal: 'Agency inventory',
					days_listed: l.days_live,
					price_cuts: 1,
					watch: false,
					matched: l.matched
				}
			}
		},
		owners: {
			...base.owners,
			get: async (id) => find(owners, id),
			list: async (p) => {
				const rows = owners.filter(
					(o) =>
						p.ownership !== 'former' &&
						(!p.list_id || rowsForImport(p.list_id).some((row) => row.ownerKey === o.id)) &&
						(!p.q || `${o.name} ${o.units.join(' ')}`.toLowerCase().includes(p.q.toLowerCase())) &&
						(!p.area || o.unit_rows.some((u) => u.area === p.area)) &&
						(p.tab === 'mine'
							? o.mine
							: p.tab === 'multi'
								? o.units_total > 1
								: p.tab === 'update'
									? o.market_update_due
									: !(p.tab === 'sold' || p.tab === 'review'))
				)
				const offset = p.offset ?? 0
				const limit = p.limit ?? 50
				return structuredClone({
					items: rows.slice(offset, offset + limit),
					pageFiltered: false,
					areas: locations.map((l) => l[0]),
					page: {
						offset,
						limit,
						total: rows.length,
						loaded: rows.slice(offset, offset + limit).length
					}
				})
			},
			historySummary: async (importId) => {
				if (importId === undefined) return structuredClone(historySummary)
				const count = rowsForImport(importId).length
				return {
					...historySummary,
					source_event_count: count,
					identifiable_property_count: count,
					owner_property_count: count,
					verified_current_count: count
				}
			},
			history: async (id, p = {}) => {
				const owner = find(owners, id)
				return {
					owner_key: id,
					summary: {
						...historySummary,
						source_event_count: owner.units_total,
						identifiable_property_count: owner.units_total,
						owner_property_count: owner.units_total,
						verified_current_count: owner.units_current
					},
					events: [],
					total: 0,
					limit: p.limit ?? 50,
					offset: p.offset ?? 0
				}
			}
		},
		imports: {
			...base.imports,
			list: async () => [
				{
					id: '950002',
					who: agents[0],
					kind: 'Leads',
					jobStatus: 'completed',
					file: 'residential-enquiries.csv',
					rows: leads.length,
					areas: 'Dubai Marina · Downtown Dubai · Business Bay',
					at: date(-2),
					status: 'Completed',
					tone: 'green'
				}
			],
			ownerHistory: async () =>
				ownerFiles.map((file) => ({
					id: file.id,
					name: file.name,
					file: file.file,
					status: file.status,
					claims: file.counts.kept,
					rentalLeads: renewals.filter((lease) =>
						rowsForImport(file.id).some((row) => `${row.building} #${row.unit}` === lease.unit)
					).length,
					at: file.at
				})),
			ownerDetails: async () => structuredClone(ownerFiles),
			ownerRows: async (id, p) => {
				const rows = rowsForImport(id).filter(
					(r) =>
						(!p.search ||
							`${r.name} ${r.building} ${r.unit} ${r.area}`
								.toLowerCase()
								.includes(p.search.toLowerCase())) &&
						(!p.status || r.status === p.status) &&
						(!p.matchColour?.length || p.matchColour.includes(r.matchColour ?? 'grey')) &&
						(!p.matchOutcome?.length || p.matchOutcome.includes(r.matchOutcome ?? ''))
				)
				return structuredClone({
					rows: rows.slice(p.offset, p.offset + 50),
					total: rows.length,
					offset: p.offset,
					limit: 50
				})
			},
			ownerDropped: async (id, p) => {
				find(ownerFiles, id)
				return {
					available: true,
					rows: [],
					byReason: {},
					total: 0,
					offset: p.offset,
					limit: 50
				}
			},
			ownerProperties: async (id, p) => {
				const rows: T.OwnerProperty[] = rowsForImport(id)
					.filter(
						(r) =>
							!p.search || `${r.name} ${r.building}`.toLowerCase().includes(p.search.toLowerCase())
					)
					.map((r) => ({
						key: String(r.id),
						area: r.area,
						project: r.project,
						building: r.building,
						unit: r.unit,
						type: r.propertyType,
						rows: 1,
						buyers: 1,
						sellers: 0,
						currentOwner: r.name,
						latestDate: r.date,
						latestPrice: r.price,
						records: [
							{
								name: r.name,
								procedure: 'Sale',
								identifiers: {},
								propertyDetails: {},
								matchReason: r.reason,
								role: 'Buyer',
								date: r.date,
								price: r.price,
								status: r.status,
								sheet: r.sheet,
								rowNumber: r.rowNumber
							}
						],
						recordsTruncated: false
					}))
				return {
					rows: rows.slice(p.offset, p.offset + 50),
					total: rows.length,
					offset: p.offset,
					limit: 50
				}
			}
		},
		events: {
			...base.events,
			list: async (from, to) =>
				structuredClone(events.filter((e) => e.date >= from && e.date <= to)),
			get: async (id) => find(events, id),
			side: async () => ({
				overdue: leads
					.slice(0, 2)
					.map((l) => ({ text: 'Follow-up due', detail: l.name, lead_id: l.id })),
				deadlines: events
					.filter((e) => e.date >= today)
					.slice(0, 4)
					.map((event) => ({ event: structuredClone(event), chip: chip('Upcoming', 'blue') }))
			})
		},
		search: async (q) => {
			const contains = (text: string) => text.toLowerCase().includes(q.toLowerCase())
			return structuredClone({
				leads: leads.filter((l) => contains(l.name)),
				deals: deals.filter((d) => contains(`${d.client} ${d.unit}`)),
				listings: listings.filter((l) => contains(l.unit)),
				owners: owners.filter((o) => contains(o.name)),
				units: owners.flatMap((o) =>
					o.unit_rows
						.filter((u) => contains(`${u.building} ${u.number}`))
						.map((u) => ({
							owner_id: o.id,
							owner_name: o.name,
							unit: `${u.building} #${u.number}`,
							area: u.area
						}))
				)
			})
		},
		notifications: { ...base.notifications, list: async () => structuredClone(notifications) },
		connections: async () => structuredClone(connections)
	}
}
