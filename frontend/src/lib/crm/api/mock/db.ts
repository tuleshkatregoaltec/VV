/**
 * In-memory tables for fixture mode, seeded from ./fixtures.json (a copy of
 * docs/crm/reference/fixtures.json from the handoff). What the 1 Oct reference mockup adds on top
 * of the fixtures is filled in here: lead ↔ listing links (3 → L1, 9 → L13, 14 → L5), listing
 * L13, notification targets, owner ids, phones and units, viewing addresses, and one deal of
 * Sara's in each compliance state. State lives for the browser session; a reload resets it.
 *
 * CRM v2 (7 Oct): `vitevue` lead sources become `file` ("Your owner file") and owner sources
 * become Agency file + DLD/Ejari event — Vitevue never supplies an owner. Owners carry prior
 * transactions added with Add record. Added from the v2 mockup: Jonas Weber (owner on the file
 * with no prior deal on record, and his landlord lead) and Anastasia Petrova as an off-plan buyer.
 */
import type {
	Approval,
	DealType,
	EventKind,
	InvoiceStatus,
	LeadFields,
	LeadStage,
	LeadType,
	ListingScope,
	ListingStatus,
	Origin,
	OwnerSource,
	PursuedMatch,
	RefKind,
	Source
} from '../types'
import fixtures from './fixtures.json'
import { ALLOCATIONS, inboxItems, PROJECTS, unitEvents } from './matchdata'
import { TODAY } from './rules'

export const ME = fixtures.me

export interface DbOwnerMatch {
	unit: string
	area: string
	status: string
	purchase: string
	owner_name: string | null
}

export interface DbLead {
	id: number
	name: string
	phone: string
	lead_type: LeadType
	source: Source
	source_detail: string
	received_label: string
	stage: LeadStage
	agent: string | null
	score: number
	area: string
	language: string
	next_action: string
	listing_id: string | null
	own_listing_id: string | null
	off_plan: boolean
	fields: LeadFields
	owner_match: { summary: string; records: DbOwnerMatch[] }
	suggested_agent: { name: string; reason: string } | null
	last_activity: string
	last_activity_text: string
	viewing_outcome_due: string | null
	form_i_on_file: boolean
	first_call_logged: boolean
	/** Documents a stage asked for (passport, Form B…). */
	documents: DbDoc[]
	/** The owner record behind the lead (owner file or own contact). */
	owner_id: string | null
	offer: { amount_aed: number; listing_id: string | null; from: string } | null
}

export interface DbLeadEvent {
	id: number
	lead_id: number
	at: string
	text: string
	origin: Origin
	token: string | null
	reverted: boolean
}

export interface DbDoc {
	id: number
	type: string
	file: string
	size_bytes: number
	uploaded: string
}

export interface DbDeal {
	id: string
	deal_type: DealType
	unit: string
	client: string
	counterparty: string
	value_aed: number
	stage_index: number
	agent: string
	lead_id: number | null
	listing_id: string | null
	due_date: string
	next_step: string
	approval: Approval
	documents: DbDoc[]
	commission: {
		rate_pct: number
		cobroker_pct: number
		referral_pct: number
		agent_pct: number
		invoice_status: InvoiceStatus
		cobroker_name: string | null
		referral_name: string | null
	}
	compliance: {
		due_diligence: 'pending' | 'complete'
		screening: 'not_run' | 'running' | 'clear' | 'review'
		cash_aed: number
	}
	dld_transaction_id: string | null
	/** Conveyancing ticks set by hand, keyed "stage:item". */
	checks: Record<string, boolean>
}

export interface DbListing {
	id: string
	unit: string
	area: string
	bedrooms: number
	size_sqft: number
	price_aed: number
	deal_type: DealType
	status: ListingStatus
	scope: ListingScope
	agent: string
	owner: string
	portals: string
	days_live: number
	enquiries: number
	permit: { number: string; expires: string } | null
	form_a_expires: string | null
	comparables_note: string
	documents: DbDoc[]
	from_lead_id: number | null
}

export interface DbOwnerUnit {
	number: string
	building: string
	area: string
	type: string
	bedrooms: number | null
	size_sqft: number | null
	bought_aed: number | null
	bought_year: number | null
	status: string
	rent: { aed: number; from: string; to: string } | null
	market: { sale: [number, number]; rent: [number, number] } | null
	rent_history: [number, number][]
	transactions: [string, string, number][]
}

export interface DbOwner {
	id: string
	name: string
	phone: string | null
	sources: OwnerSource[]
	units: DbOwnerUnit[]
	next_event: string
	next_event_date: string
	last_contact: string
	tag: string
	market_update_due: boolean
	notes: { id: number; at: string; text: string; origin: Origin }[]
	/** Prior transactions on the agency's file (Add record). */
	prior: DbPrior[]
}

export interface DbPrior {
	id: number
	kind: 'sale' | 'tenancy' | 'listing_agreement'
	date: string
	unit: string
	reference: string
	/** Added in this session with Add record. */
	added: boolean
}

export interface DbEvent {
	id: number
	date: string
	time: string | null
	kind: EventKind
	title: string
	detail: string
	agent: string
	lead_id: number | null
	deal_id: string | null
	listing_id: string | null
	owner_id: string | null
	done: boolean
}

export interface DbRenewal {
	id: number
	party: string
	unit: string
	rent_aed: number
	building_median_aed: number
	lease_end: string
	started: boolean
	deal_id: string | null
}

export interface DbMarket {
	id: string
	unit: string
	area: string
	deal_type: DealType
	price_aed: number
	value_from_comparables_aed: number
	discount_pct: number
	portal: string
	days_listed: number
	price_cuts: number
	watch: boolean
}

export interface DbImport {
	id: string
	who: string
	kind: 'Owners' | 'Leads'
	file: string
	rows: number
	areas: string
	at: string
	status: string
}

export interface DbNotification {
	id: number
	text: string
	detail: string
	unread: boolean
	ref: { kind: RefKind; id: string } | null
}

export interface DbConnection {
	id: string
	name: string
	detail: string
	status: string
	kind: 'source' | 'import'
}

export interface DbPortfolioRow {
	client: string
	what: string
	unit: string
	value_aed: number
	date: string
	dld_or_ejari: string
	commission_aed: number
}

let seq = 1000
export function nextId(): number {
	seq += 1
	return seq
}

const normInvoice = (s: string): InvoiceStatus =>
	(s.replace(' ', '_') as InvoiceStatus) || 'not_invoiced'
const normScreening = (s: string) =>
	(s.toLowerCase().replace(' ', '_') as DbDeal['compliance']['screening']) || 'not_run'
const docId = () => nextId()

/* Every unit an owner holds (DLD + Ejari), from the 1 Oct mockup. Same fields for every owner. */
type U = [
	number: string,
	building: string,
	area: string,
	beds: number,
	sqft: number,
	bought: number,
	year: number,
	status: string,
	rent: [number, string, string] | null,
	market: [[number, number], [number, number]],
	history: [number, number][],
	tx: [string, string, number][]
]
const unit = (u: U): DbOwnerUnit => ({
	number: u[0],
	building: u[1],
	area: u[2],
	type: 'Apartment',
	bedrooms: u[3],
	size_sqft: u[4],
	bought_aed: u[5],
	bought_year: u[6],
	status: u[7],
	rent: u[8] ? { aed: u[8][0], from: u[8][1], to: u[8][2] } : null,
	market: { sale: u[9][0], rent: u[9][1] },
	rent_history: u[10],
	transactions: u[11]
})

const OWNER_UNITS: Record<string, U[]> = {
	'Mariam Al Falasi': [
		[
			'2304',
			'Marina Gate 2',
			'Dubai Marina',
			2,
			1180,
			2650000,
			2017,
			'Let · ends 9 Nov 2026',
			[165000, '2025-11-10', '2026-11-09'],
			[
				[3200000, 3450000],
				[170000, 185000]
			],
			[
				[2022, 140000],
				[2023, 150000],
				[2024, 158000],
				[2025, 165000]
			],
			[
				['2017', 'Bought', 2650000],
				['2025', 'Lease renewed', 165000]
			]
		],
		[
			'412',
			'Bellavista',
			'JVC',
			1,
			720,
			720000,
			2020,
			'Vacant since Aug 2026',
			null,
			[
				[820000, 900000],
				[80000, 88000]
			],
			[
				[2022, 62000],
				[2023, 70000],
				[2024, 76000],
				[2025, 80000]
			],
			[
				['2020', 'Bought', 720000],
				['Aug 2026', 'Tenant moved out', 0]
			]
		],
		[
			'1907',
			'Executive Tower J',
			'Business Bay',
			1,
			760,
			1050000,
			2018,
			'Let · ends Apr 2027',
			[98000, '2026-05-01', '2027-04-30'],
			[
				[1350000, 1500000],
				[95000, 105000]
			],
			[
				[2023, 82000],
				[2024, 90000],
				[2025, 94000],
				[2026, 98000]
			],
			[
				['2018', 'Bought', 1050000],
				['2026', 'Lease renewed', 98000]
			]
		]
	],
	'Rashid Al Noori': [
		[
			'207',
			'Bellavista',
			'JVC',
			1,
			700,
			610000,
			2016,
			'Let · ends Feb 2027',
			[78000, '2026-03-01', '2027-02-28'],
			[
				[800000, 880000],
				[78000, 86000]
			],
			[
				[2023, 64000],
				[2024, 70000],
				[2025, 74000],
				[2026, 78000]
			],
			[['2016', 'Bought', 610000]]
		],
		[
			'1103',
			'Lake Terrace',
			'JLT',
			1,
			820,
			800000,
			2015,
			'Sold Sep 2026',
			null,
			[
				[1000000, 1080000],
				[90000, 98000]
			],
			[],
			[
				['2015', 'Bought', 800000],
				['Sep 2026', 'Sold', 1020000]
			]
		]
	],
	'Grace Mensah': [
		[
			'1506',
			'Zada Tower',
			'JVC',
			2,
			1040,
			1380000,
			2022,
			'Vacant since Aug 2026',
			null,
			[
				[1490000, 1600000],
				[85000, 92000]
			],
			[
				[2023, 78000],
				[2024, 84000],
				[2025, 86000]
			],
			[
				['2022', 'Bought', 1380000],
				['Aug 2026', 'Ejari ended', 0]
			]
		]
	],
	'Aisha Karim': [
		[
			'615',
			'Bellavista',
			'JVC',
			1,
			720,
			700000,
			2019,
			'Let · ends 26 Nov 2026',
			[82000, '2025-11-27', '2026-11-26'],
			[
				[820000, 900000],
				[84000, 90000]
			],
			[
				[2023, 70000],
				[2024, 76000],
				[2025, 82000]
			],
			[['2019', 'Bought', 700000]]
		]
	],
	'Faris Nasser': [
		[
			'301',
			'Bellavista',
			'JVC',
			1,
			720,
			650000,
			2018,
			'Let · ends 27 Oct 2026',
			[82000, '2025-10-28', '2026-10-27'],
			[
				[820000, 900000],
				[85000, 88000]
			],
			[
				[2023, 70000],
				[2024, 76000],
				[2025, 82000]
			],
			[
				['2018', 'Bought', 650000],
				['Sep 2026', 'Listed for rent at 85,000', 85000]
			]
		],
		[
			'808',
			'Creek Rise',
			'Creek Harbour',
			1,
			760,
			1050000,
			2019,
			'Sold Jun 2026',
			null,
			[
				[1250000, 1350000],
				[95000, 105000]
			],
			[],
			[
				['2019', 'Bought', 1050000],
				['Jun 2026', 'Sold', 1300000]
			]
		]
	],
	'Yusuf Rahman': [
		[
			'101',
			'Bloom Towers',
			'JVC',
			0,
			410,
			420000,
			2018,
			'Let · ends Mar 2027',
			[50000, '2026-04-01', '2027-03-31'],
			[
				[480000, 520000],
				[50000, 55000]
			],
			[
				[2024, 44000],
				[2025, 47000],
				[2026, 50000]
			],
			[['2018', 'Bought', 420000]]
		],
		[
			'102',
			'Bloom Towers',
			'JVC',
			0,
			410,
			420000,
			2018,
			'Let · ends Jan 2027',
			[52000, '2026-02-01', '2027-01-31'],
			[
				[480000, 520000],
				[50000, 55000]
			],
			[
				[2024, 45000],
				[2025, 48000],
				[2026, 52000]
			],
			[['2018', 'Bought', 420000]]
		],
		[
			'305',
			'Bloom Towers',
			'JVC',
			1,
			700,
			610000,
			2019,
			'Let · ends Jun 2027',
			[72000, '2026-07-01', '2027-06-30'],
			[
				[760000, 820000],
				[72000, 78000]
			],
			[
				[2024, 64000],
				[2025, 68000],
				[2026, 72000]
			],
			[['2019', 'Bought', 610000]]
		],
		[
			'904',
			'Zada Tower',
			'JVC',
			1,
			760,
			700000,
			2021,
			'Let · ends Dec 2026',
			[76000, '2026-01-01', '2026-12-31'],
			[
				[880000, 950000],
				[76000, 82000]
			],
			[
				[2024, 68000],
				[2025, 72000],
				[2026, 76000]
			],
			[['2021', 'Bought', 700000]]
		],
		[
			'1101',
			'Bellavista',
			'JVC',
			2,
			1150,
			1150000,
			2020,
			'Let · ends Aug 2027',
			[110000, '2026-09-01', '2027-08-31'],
			[
				[1350000, 1450000],
				[105000, 115000]
			],
			[
				[2024, 96000],
				[2025, 104000],
				[2026, 110000]
			],
			[['2020', 'Bought', 1150000]]
		],
		[
			'1402',
			'Binghatti Hills',
			'JVC',
			1,
			690,
			890000,
			2024,
			'Off-plan · handover Feb 2027',
			null,
			[
				[950000, 1020000],
				[75000, 82000]
			],
			[],
			[['2024', 'Bought off-plan', 890000]]
		]
	],
	'Elena Petrova': [
		[
			'1210',
			'Creek Rise',
			'Creek Harbour',
			2,
			1150,
			1750000,
			2021,
			'Owner-occupied · mortgage reprices Nov 2026',
			null,
			[
				[2100000, 2300000],
				[140000, 155000]
			],
			[],
			[['2021', 'Bought with a mortgage', 1750000]]
		]
	],
	'Hamdan S.': [
		[
			'3402',
			'Burj Vista 1',
			'Downtown',
			3,
			1900,
			4900000,
			2016,
			'Owner-occupied · listing as pocket',
			null,
			[
				[7400000, 7900000],
				[380000, 420000]
			],
			[],
			[
				['2016', 'Bought', 4900000],
				['Sep 2026', 'Pocket listing at 7.8m', 7800000]
			]
		],
		[
			'2105',
			'Burj Vista 1',
			'Downtown',
			2,
			1350,
			3100000,
			2017,
			'Let · ends May 2027',
			[175000, '2026-06-01', '2027-05-31'],
			[
				[4300000, 4700000],
				[175000, 195000]
			],
			[
				[2024, 150000],
				[2025, 165000],
				[2026, 175000]
			],
			[['2017', 'Bought', 3100000]]
		],
		[
			'1810',
			'Boulevard Point',
			'Downtown',
			1,
			880,
			1650000,
			2018,
			'Let · ends Feb 2027',
			[115000, '2026-03-01', '2027-02-28'],
			[
				[2100000, 2300000],
				[115000, 125000]
			],
			[
				[2024, 100000],
				[2025, 108000],
				[2026, 115000]
			],
			[['2018', 'Bought', 1650000]]
		],
		[
			'904',
			'29 Boulevard T1',
			'Downtown',
			2,
			1240,
			2350000,
			2019,
			'Let · ends Oct 2027',
			[160000, '2026-11-01', '2027-10-31'],
			[
				[3000000, 3300000],
				[155000, 170000]
			],
			[
				[2024, 140000],
				[2025, 150000],
				[2026, 160000]
			],
			[['2019', 'Bought', 2350000]]
		]
	]
}

/* v2 mockup: an owner on the agency's file with no prior deal on record (Oxford Residence 905). */
OWNER_UNITS['Jonas Weber'] = [
	[
		'905',
		'Oxford Residence',
		'JVC',
		1,
		760,
		690000,
		2019,
		'Vacant since 2 Aug 2026',
		null,
		[
			[820000, 880000],
			[78000, 84000]
		],
		[
			[2023, 68000],
			[2024, 72000],
			[2025, 76000]
		],
		[
			['2019', 'Bought', 690000],
			['Aug 2026', 'Tenant moved out', 0]
		]
	]
]

/** Owner phones (owner data). Four match the leads they became; the rest are sample numbers. */
const OWNER_PHONES: Record<string, string> = {
	'Mariam Al Falasi': '+971 50 227 9031',
	'Rashid Al Noori': '+971 55 610 2287',
	'Grace Mensah': '+971 56 330 1142',
	'Aisha Karim': '+971 56 804 1176',
	'Faris Nasser': '+971 50 118 2290',
	'Yusuf Rahman': '+971 52 440 6631',
	'Elena Petrova': '+971 58 770 1203',
	'Hamdan S.': '+971 50 615 4402',
	'Jonas Weber': '+971 55 902 3318'
}

const JONAS = {
	name: 'Jonas Weber',
	source: 'agency_import+dld_event',
	next_event: 'Vacant since August',
	next_event_date: '2026-08-02',
	last_contact: 'Never',
	tag: 'Vacant',
	market_update_due: false
}

/** Owner sources (7 Oct): what was "Vitevue data" is the agency's own file plus a DLD/Ejari event. */
const ownerSources = (s: string): OwnerSource[] => [
	...new Set(
		s
			.split('+')
			.flatMap((x) => (x === 'vitevue' ? ['agency_import', 'dld_event'] : [x])) as OwnerSource[]
	)
]

function seedOwners(): DbOwner[] {
	return [...fixtures.owners, JONAS].map((o, i) => ({
		id: `O${i + 1}`,
		name: o.name,
		phone: OWNER_PHONES[o.name] ?? null,
		sources: ownerSources(o.source),
		units: (OWNER_UNITS[o.name] ?? []).map(unit),
		next_event: o.next_event,
		next_event_date: o.next_event_date,
		last_contact: o.last_contact,
		tag: o.tag ?? '',
		market_update_due: o.market_update_due,
		notes: [],
		prior: []
	}))
}

/**
 * Owner data (agency imports + DLD/Ejari) keyed by phone: what a phone number matches. The
 * fixture leads' owner_match blocks are the results of this lookup, so they seed it; the owners
 * table adds its own numbers.
 */
function seedOwnerData(owners: DbOwner[]): Record<string, DbLead['owner_match']> {
	const out: Record<string, DbLead['owner_match']> = {}
	for (const o of owners) {
		if (!o.phone || !o.units.length) continue
		out[o.phone] = {
			summary: `Owns ${o.units.length} unit${o.units.length > 1 ? 's' : ''}`,
			records: o.units.map((u) => ({
				unit: `${u.building} #${u.number} · ${u.bedrooms ? `${u.bedrooms}BR` : 'Studio'}`,
				area: u.area,
				status: u.status,
				purchase: u.bought_aed
					? `Bought ${u.bought_year} · AED ${u.bought_aed.toLocaleString('en-US')}`
					: '',
				owner_name: o.name
			}))
		}
	}
	for (const l of LEADS) {
		if (l.owner_match.records.length && l.source !== 'agent_to_agent') {
			out[l.phone] = {
				summary: l.owner_match.summary,
				records: l.owner_match.records.map((r) => ({ ...r }))
			}
		}
	}
	return out
}

/** Portal leads and the listing they enquired on (the mockup adds Sofia → L13, James → L5). */
const ENQUIRED_ON: Record<number, string> = { 9: 'L13', 14: 'L5' }

/** v2 mockup: Jonas Weber's landlord lead from the owner file, no prior deal on record. */
const JONAS_LEAD = {
	id: 20,
	name: 'Jonas Weber',
	phone: '+971 55 902 3318',
	lead_type: 'landlord',
	source: 'vitevue',
	source_detail: 'Vacant since 2 Aug · Oxford Residence 905',
	received_label: 'Mon 28 Sep',
	stage: 'new',
	agent: 'Sara A.',
	score: 58,
	area: 'JVC',
	language: 'English',
	next_action: 'Add a prior deal record before contacting',
	listing_id: null,
	cold: false,
	fields: { unit: 'Oxford Residence 905 · 1BR', expected_rent_aed: 80000, available: 'Now' },
	owner_match: {
		summary: 'Owns 1 unit in JVC · vacant',
		records: [
			{
				unit: 'Oxford Residence #905 · 1BR',
				area: 'JVC',
				status: 'Vacant since 2 Aug 2026',
				purchase: 'Bought 2019 · AED 690,000',
				owner_name: 'Jonas Weber'
			}
		]
	},
	suggested_agent: null,
	history: [
		{ at: 'Mon 28 Sep', change: 'Lead created from your owner file · vacant unit', origin: 'rule' },
		{ at: '+1 min', change: 'No prior deal with this owner on record', origin: 'rule' }
	]
}
const LEADS = [...fixtures.leads, JONAS_LEAD]

/**
 * Off-plan buyers (7 Oct, planned): Anastasia Petrova's enquiry was a Downtown launch, so she is
 * matched to Launch desk projects on areas, from-price, on-booking amount and handover date.
 */
const OFF_PLAN: Record<number, LeadFields> = {
	2: { areas: 'Downtown, Business Bay', on_booking_aed: 360000, handover_by: '2028-06-30' }
}

/** "On your agency's file" (7 Oct): the phone is checked against the agency's own owner file. */
const fileWording = (s: string) =>
	s === 'No match in owner data' ? "Not on your agency's file" : s

function seedLeads(owners: DbOwner[]): DbLead[] {
	return LEADS.map((l) => ({
		id: l.id,
		name: l.name,
		phone: l.phone,
		lead_type: l.lead_type as LeadType,
		source: (l.source === 'vitevue' ? 'file' : l.source) as Source,
		source_detail: l.source_detail,
		received_label: l.received_label,
		stage: l.stage as LeadStage,
		agent: l.agent,
		score: l.score,
		area: l.area,
		language: l.language,
		next_action: l.next_action,
		listing_id: l.listing_id ?? ENQUIRED_ON[l.id] ?? null,
		// The mockup links Mariam Al Falasi's seller lead to the listing it became (L1).
		own_listing_id: l.id === 3 ? 'L1' : null,
		off_plan: Boolean(OFF_PLAN[l.id]),
		fields: { ...(l.fields as LeadFields), ...OFF_PLAN[l.id] },
		owner_match: {
			summary: fileWording(l.owner_match.summary),
			records: l.owner_match.records.map((r) => ({ ...r }))
		},
		suggested_agent: l.suggested_agent,
		// Anastasia Petrova (2) has gone quiet for 5 days; Sofia Rossi (9) had a viewing on
		// Sat 26 Sep with no outcome logged. Both feed Overdue and Gaps.
		last_activity: l.id === 2 ? '2026-09-24' : TODAY,
		last_activity_text: l.id === 2 ? 'payment plan requested' : '',
		viewing_outcome_due: l.id === 9 ? '2026-09-26' : null,
		form_i_on_file: false,
		first_call_logged: l.stage !== 'new',
		documents: [],
		owner_id: owners.find((o) => o.phone === l.phone)?.id ?? null,
		offer: null
	}))
}

function seedLeadEvents(): DbLeadEvent[] {
	const out: DbLeadEvent[] = []
	for (const l of LEADS) {
		for (const h of l.history) {
			out.push({
				id: nextId(),
				lead_id: l.id,
				at: h.at,
				text: h.change,
				origin: h.origin as Origin,
				token: null,
				reverted: false
			})
		}
	}
	return out
}

/**
 * In the fixtures every one of Sara's deals is complete and clear, so Mark complete, Run check
 * and goAML never show on her own deals. One deal per state: DL-204 due diligence pending and
 * screening not run, DL-201 screening needs review, DL-203 part-paid in cash (goAML).
 */
const COMPLIANCE: Record<string, Partial<DbDeal['compliance']>> = {
	'DL-204': { due_diligence: 'pending', screening: 'not_run' },
	'DL-201': { screening: 'review' },
	'DL-203': { cash_aed: 80000 }
}

/** Ticks set by hand. DL-205 is at Ejari with "Register Ejari" still to do. */
const CHECKS: Record<string, Record<string, boolean>> = { 'DL-205': { '2:0': false } }

function seedDeals(): DbDeal[] {
	return fixtures.deals.map((d) => ({
		id: d.id,
		deal_type: d.deal_type as DealType,
		unit: d.unit,
		client: d.client,
		counterparty: d.counterparty,
		value_aed: d.value_aed,
		stage_index: d.stage_index,
		agent: d.agent,
		lead_id: d.lead_id,
		listing_id: d.listing_id,
		due_date: d.due_date,
		next_step: d.next_step,
		approval: d.approval as Approval,
		documents: d.documents.received.map((r) => ({
			id: docId(),
			type: r.type,
			file: r.file,
			size_bytes: r.size_bytes,
			uploaded: r.uploaded
		})),
		commission: {
			rate_pct: d.commission.rate_pct,
			cobroker_pct: d.commission.cobroker_pct,
			referral_pct: d.commission.referral_pct,
			agent_pct: d.commission.agent_pct,
			invoice_status: normInvoice(d.commission.invoice_status),
			cobroker_name: d.commission.cobroker_name,
			referral_name: d.commission.referral_name
		},
		compliance: {
			due_diligence: d.compliance.due_diligence === 'Complete' ? 'complete' : 'pending',
			screening: normScreening(d.compliance.screening),
			cash_aed: d.compliance.cash_aed,
			...COMPLIANCE[d.id]
		},
		dld_transaction_id: d.dld_transaction_id,
		checks: { ...CHECKS[d.id] }
	}))
}

/** Sofia Rossi's portal enquiry was on this listing (1 Oct mockup). */
const L13 = {
	id: 'L13',
	unit: 'Bay Square 7 · 1BR',
	area: 'Business Bay',
	bedrooms: 1,
	size_sqft: 780,
	price_aed: 98000,
	deal_type: 'rent',
	status: 'live',
	scope: 'mine',
	agent: 'Sara A.',
	owner: 'Omar Haddad',
	portals: 'PF · Bayut',
	days_live: 6,
	enquiries: 3,
	permit: { number: '8344••', expires: '2026-12-20' },
	form_a_expires: null,
	comparables_note: 'Building median rent 96k',
	documents: [
		{ type: 'Form A', file: 'form-a-signed.pdf', size_bytes: 420000, uploaded: '22 Sep' },
		{ type: 'Title deed', file: 'title-deed.pdf', size_bytes: 1100000, uploaded: '22 Sep' },
		{ type: 'Photos', file: 'photos-12.zip', size_bytes: 18400000, uploaded: '23 Sep' }
	]
}

/** L3 and L4 carry a Form A expiry, so the signed Form A is on file. */
const FORM_A_ON_FILE = ['L3', 'L4']

function seedListings(): DbListing[] {
	return [...fixtures.listings, L13].map((x) => ({
		id: x.id,
		unit: x.unit,
		area: x.area,
		bedrooms: x.bedrooms,
		size_sqft: x.size_sqft,
		price_aed: x.price_aed,
		deal_type: x.deal_type as DealType,
		status: x.status as ListingStatus,
		scope: x.scope as ListingScope,
		agent: x.agent,
		owner: x.owner,
		portals: x.portals,
		days_live: x.days_live,
		enquiries: x.enquiries,
		permit: x.permit,
		form_a_expires: x.form_a_expires,
		comparables_note: x.comparables_note,
		documents: [
			...(FORM_A_ON_FILE.includes(x.id)
				? [{ type: 'Form A', file: 'form-a-signed.pdf', size_bytes: 420000, uploaded: '22 Sep' }]
				: []),
			...x.documents
		].map((r) => ({
			id: docId(),
			type: r.type === 'Owner passport' ? 'Owner ID' : r.type,
			file: r.file,
			size_bytes: r.size_bytes,
			uploaded: r.uploaded
		})),
		from_lead_id: x.id === 'L1' ? 3 : null
	}))
}

/** Viewings show the unit and the address, not just "Business Bay 1BR" (1 Oct). */
const EVENT_DETAIL: Record<string, { detail: string; listing_id?: string }> = {
	'Viewing — Sofia Rossi': {
		detail: 'Bay Square 7 · unit 412 · 1BR · Business Bay',
		listing_id: 'L13'
	},
	'Viewing — Chen Wei': { detail: 'Bloom Towers · unit 1104 · 1BR · JVC' },
	'Private viewing — Olga Ivanova': {
		detail: 'Palm Tiara · Penthouse 4501 · Palm Jumeirah',
		listing_id: 'L9'
	}
}

function seedEvents(owners: DbOwner[]): DbEvent[] {
	return fixtures.calendar_events.map((e) => {
		const owner = owners.find((o) => e.title.includes(o.name))
		const extra = EVENT_DETAIL[e.title]
		return {
			id: nextId(),
			date: e.date,
			time: e.time,
			kind: e.kind as EventKind,
			title: e.title,
			detail: extra?.detail ?? e.detail,
			agent: e.agent,
			lead_id: e.lead_id,
			deal_id: e.deal_id,
			listing_id: extra?.listing_id ?? e.listing_id,
			owner_id: !e.lead_id && !e.deal_id && !e.listing_id && owner ? owner.id : null,
			done: false
		}
	})
}

const NOTIFICATION_REFS: ({ kind: RefKind; id: string } | null)[] = [
	{ kind: 'lead', id: '3' },
	{ kind: 'lead', id: '7' },
	{ kind: 'listing', id: 'L2' },
	{ kind: 'deal', id: 'DL-203' },
	{ kind: 'deal', id: 'DL-205' }
]

/** Sources (7 Oct): six sources, status only — the Inbox's Sources card replaces Connections. */
const CONNECTIONS: DbConnection[] = [
	{ id: 'c1', name: 'Bayut', detail: 'Portal enquiries', status: 'Connected', kind: 'source' },
	{ id: 'c2', name: 'Dubizzle', detail: 'Portal enquiries', status: 'Connected', kind: 'source' },
	{
		id: 'c3',
		name: 'Instagram',
		detail: 'Direct messages to the agency account',
		status: 'Connected',
		kind: 'source'
	},
	{
		id: 'c4',
		name: 'Email',
		detail: 'Forwarded enquiries and website form',
		status: 'Connected',
		kind: 'source'
	},
	{
		id: 'c5',
		name: 'Property Finder',
		detail: 'Portal enquiries',
		status: 'Applying',
		kind: 'source'
	},
	{
		id: 'c6',
		name: 'WhatsApp Business',
		detail: "Messages to the agency's business number",
		status: 'Needs a business number',
		kind: 'source'
	}
]

function seedPortfolio(): DbPortfolioRow[] {
	return fixtures.portfolio.flatMap((p) =>
		p.transactions.map((t) => ({
			client: p.client,
			what: t.what,
			unit: t.unit,
			value_aed: t.value_aed,
			date: t.date,
			dld_or_ejari: t.dld_or_ejari,
			commission_aed: t.commission_aed
		}))
	)
}

function build() {
	const owners = seedOwners()
	return {
		areas: ['Dubai Marina', 'JVC'] as string[],
		/** Areas used for Assets → Market (the agent's working areas). */
		marketAreas: ['Dubai Marina', 'JVC', 'Business Bay', 'Dubai Hills'] as string[],
		agents: fixtures.agents,
		leads: seedLeads(owners),
		ownerData: seedOwnerData(owners),
		leadEvents: seedLeadEvents(),
		deals: seedDeals(),
		listings: seedListings(),
		owners,
		events: seedEvents(owners),
		portfolio: seedPortfolio(),
		renewals: fixtures.renewals.map((r, i) => ({
			id: i + 1,
			...r,
			started: false,
			deal_id: null
		})) as DbRenewal[],
		market: fixtures.market_listings.map((m) => ({
			...m,
			deal_type: m.deal_type as DealType,
			watch: false
		})) as DbMarket[],
		imports: fixtures.import_requests.map((r) => ({
			id: r.id,
			who: r.who,
			kind: r.kind as 'Owners' | 'Leads',
			file: r.file,
			rows: r.rows,
			areas: r.areas,
			at: r.at,
			status: r.st
		})) as DbImport[],
		feedAreas: fixtures.feed_areas,
		notifications: fixtures.notifications.map((n, i) => ({
			id: i + 1,
			text: n.text,
			// 7 Oct: an owner lead comes from the agency's own file, never "from Vitevue".
			detail: n.detail.replace(/^Vitevue · /, 'Your owner file · '),
			unread: n.unread,
			ref: NOTIFICATION_REFS[i] ?? null
		})) as DbNotification[],
		connections: CONNECTIONS.map((c) => ({ ...c })),
		/** Pursue in Matches: per lead, the matches being pursued. */
		pursued: {} as Record<number, PursuedMatch[]>,
		/** Shortlist in Matches: per lead, match keys. */
		shortlist: {} as Record<number, string[]>,
		/** Watch unit (unit events): keys being watched. */
		watched: {} as Record<string, boolean>,
		projects: PROJECTS.map((p) => ({ ...p })),
		allocations: ALLOCATIONS.map((a) => ({ ...a })),
		unitEvents: unitEvents(),
		inbox: inboxItems(),
		/**
		 * Lead handout (6 Oct, 05:24): manager assigns · first to ask gets it · agents ask, manager
		 * confirms. Default not decided; the mockup uses Manager assigns.
		 */
		settings: {
			handout: 'manager' as 'manager' | 'request' | 'both',
			log: [] as { id: number; at: string; who: string; from: string; to: string }[]
		}
	}
}

export type Db = ReturnType<typeof build>

export const db: Db = build()

/** Test helper: put every table back to the fixture state. */
export function resetDb(): void {
	Object.assign(db, build())
}
