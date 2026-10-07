/**
 * Example data the CRM v2 mockup (7 Oct) adds for Matches and the Inbox, fitted to this fixture
 * set ("today" = 2026-09-29, signed in as Sara A.). Projects are "Example project A–F" by
 * "Developer 1–4"; every name and figure is an example. Unit events are DLD/Ejari units with a
 * lease end whose owner is not on the agency's file: they never carry an owner.
 */
import { addDays } from './rules'

export interface DbProject {
	id: string
	name: string
	developer: string
	area: string
	beds: string
	from_aed: number
	plan: string
	on_booking_aed: number
	handover: string
	handover_date: string
}

export interface DbAllocation {
	id: string
	project: string
	area: string
	unit: string
	price_aed: number
	agent: string
	left: number
}

export interface DbUnitEvent {
	id: string
	building: string
	number: string
	area: string
	bedrooms: number
	deal_type: 'sale' | 'rent'
	/** Lease end (or vacancy) date from Ejari. */
	date: string
	what: string
}

export interface DbInboxRequest {
	agent: string
	at: string
}

export interface DbInboxItem {
	id: string
	name: string
	/** Bayut, Dubizzle, Instagram, Email, Website, Your owner file… */
	source: string
	/** Source line colour. */
	line: 'in' | 'vv' | 'own' | 'a2a'
	/** YYYY-MM-DDTHH:MM, Dubai time */
	at: string
	text: string
	/** Owner check against the agency's own file. */
	owner_check: string
	priority: string
	status: 'waiting' | 'requested' | 'assigned' | 'dismissed'
	agent: string
	suggested: string
	reason: string
	requests: DbInboxRequest[]
	lead_id: number | null
	/** Assigned because the agent asked first (Release is allowed while the lead is New). */
	via_request: boolean
	want: {
		type: 'buyer' | 'seller' | 'tenant' | 'landlord'
		area: string
		beds: number | null
		budget: number | null
	} | null
}

export const PROJECTS: DbProject[] = [
	{
		id: 'PJ-A',
		name: 'Example project A',
		developer: 'Developer 1',
		area: 'JVC',
		beds: '1 and 2 bed',
		from_aed: 1040000,
		plan: '20 / 50 / 30',
		on_booking_aed: 208000,
		handover: 'Q4 2027',
		handover_date: '2027-12-31'
	},
	{
		id: 'PJ-B',
		name: 'Example project B',
		developer: 'Developer 2',
		area: 'JVC',
		beds: 'Studio to 2 bed',
		from_aed: 790000,
		plan: '10 / 60 / 30',
		on_booking_aed: 79000,
		handover: 'Q2 2028',
		handover_date: '2028-06-30'
	},
	{
		id: 'PJ-C',
		name: 'Example project C',
		developer: 'Developer 3',
		area: 'Business Bay',
		beds: '1 and 2 bed',
		from_aed: 1690000,
		plan: '20 / 40 / 40',
		on_booking_aed: 338000,
		handover: 'Q1 2029',
		handover_date: '2029-03-31'
	},
	{
		id: 'PJ-D',
		name: 'Example project D',
		developer: 'Developer 1',
		area: 'Downtown',
		beds: '2 and 3 bed',
		from_aed: 1750000,
		plan: '10 / 70 / 20',
		on_booking_aed: 175000,
		handover: 'Q3 2027',
		handover_date: '2027-09-30'
	},
	{
		id: 'PJ-E',
		name: 'Example project E',
		developer: 'Developer 4',
		area: 'Creek Harbour',
		beds: '1 to 3 bed',
		from_aed: 1890000,
		plan: '20 / 50 / 30',
		on_booking_aed: 378000,
		handover: 'Q4 2028',
		handover_date: '2028-12-31'
	},
	{
		id: 'PJ-F',
		name: 'Example project F',
		developer: 'Developer 2',
		area: 'Downtown',
		beds: '2 bed',
		from_aed: 2480000,
		plan: '10 / 50 / 40',
		on_booking_aed: 248000,
		handover: 'Q2 2028',
		handover_date: '2028-06-30'
	}
]

export const ALLOCATIONS: DbAllocation[] = [
	{
		id: 'AL-1',
		project: 'Example project D',
		area: 'Downtown',
		unit: '2 bed · 1,210 sqft · floor 14',
		price_aed: 1790000,
		agent: 'Priya N.',
		left: 6
	},
	{
		id: 'AL-2',
		project: 'Example project C',
		area: 'Business Bay',
		unit: '1 bed · 760 sqft · floor 9',
		price_aed: 1720000,
		agent: 'Sara A.',
		left: 3
	},
	{
		id: 'AL-3',
		project: 'Example project B',
		area: 'JVC',
		unit: '1 bed · 742 sqft · floor 5',
		price_aed: 815000,
		agent: 'Omar K.',
		left: 2
	}
]

/** Units with a lease ending (Ejari) whose owner is not on the agency's file: unit only, "Watch unit". */
export function unitEvents(): DbUnitEvent[] {
	const u = (
		id: string,
		building: string,
		number: string,
		area: string,
		bedrooms: number,
		deal_type: 'sale' | 'rent',
		days: number
	): DbUnitEvent => ({
		id,
		building,
		number,
		area,
		bedrooms,
		deal_type,
		date: addDays('2026-09-29', days),
		what: 'lease ends'
	})
	return [
		u('UE-1', 'Bloom Towers', '1508', 'JVC', 1, 'sale', 29),
		u('UE-2', 'Seasons Community', '210', 'JVC', 1, 'sale', 31),
		u('UE-3', 'Oxford Residence', '212', 'JVC', 1, 'sale', 51),
		u('UE-4', 'Belgravia 3', '1104', 'JVC', 1, 'sale', 76),
		u('UE-5', 'Bay Square 4', '608', 'Business Bay', 1, 'rent', 20),
		u('UE-6', 'Executive Tower B', '1402', 'Business Bay', 1, 'rent', 38),
		u('UE-7', 'Marina Promenade', '903', 'Dubai Marina', 2, 'rent', 24),
		u('UE-8', 'Al Majara 2', '1711', 'Dubai Marina', 2, 'rent', 64),
		u('UE-9', 'Creek Horizon', '507', 'Creek Harbour', 2, 'sale', 42)
	]
}

export function inboxItems(): DbInboxItem[] {
	return [
		{
			id: 'IN-31',
			name: 'Khalid Al Suwaidi',
			source: 'Website form',
			line: 'in',
			at: '2026-09-29T09:20',
			text: 'Valuation request for my 1 bed in Executive Tower, thinking of selling.',
			owner_check: "Phone matches an owner on your agency's file · 1 unit in Business Bay",
			priority: 'High · an owner',
			status: 'assigned',
			agent: 'Sara A.',
			suggested: 'Sara A.',
			reason: 'Assigned by the manager',
			requests: [],
			lead_id: 19,
			via_request: false,
			want: { type: 'seller', area: 'Business Bay', beds: 1, budget: null }
		},
		{
			id: 'IN-32',
			name: 'Rami Haddad',
			source: 'WhatsApp',
			line: 'a2a',
			at: '2026-09-29T09:05',
			text: '2BR Marina for a client, cash, November. I am an agent.',
			owner_check: 'Broker · no owner check',
			priority: 'Normal · agent for a client',
			status: 'assigned',
			agent: 'Sara A.',
			suggested: 'Sara A.',
			reason: 'Covers Dubai Marina',
			requests: [],
			lead_id: 7,
			via_request: false,
			want: { type: 'tenant', area: 'Dubai Marina', beds: 2, budget: 150000 }
		},
		{
			id: 'IN-33',
			name: 'Studio enquiry',
			source: 'Dubizzle',
			line: 'in',
			at: '2026-09-29T10:02',
			text: 'Studio in the Marina, can you send photos?',
			owner_check: "Phone matches an owner on your agency's file · 3 Marina units",
			priority: 'High · an owner',
			status: 'waiting',
			agent: 'Sara A.',
			suggested: 'Sara A.',
			reason: 'Covers Dubai Marina · first response 4 min',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'tenant', area: 'Dubai Marina', beds: 0, budget: null }
		},
		{
			id: 'IN-34',
			name: 'Jonas Weber',
			source: 'Your owner file',
			line: 'vv',
			at: '2026-09-28T07:00',
			text: 'Oxford Residence · 905 · vacant since 2 Aug',
			owner_check: "On your agency's file · no prior deal on record",
			priority: 'Normal',
			status: 'assigned',
			agent: 'Sara A.',
			suggested: 'Sara A.',
			reason: 'Your area · JVC',
			requests: [],
			lead_id: 20,
			via_request: false,
			want: null
		},
		{
			id: 'IN-35',
			name: 'Villa seller',
			source: 'Email',
			line: 'in',
			at: '2026-09-29T08:15',
			text: 'Forwarded from the website: I want to sell my villa in Arabian Ranches.',
			owner_check: "Name and phone match an owner on your agency's file · 1 villa",
			priority: 'High · a seller',
			status: 'waiting',
			agent: 'Omar K.',
			suggested: 'Omar K.',
			reason: 'Covers Arabian Ranches · speaks Arabic',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'seller', area: 'Arabian Ranches', beds: null, budget: null }
		},
		{
			id: 'IN-36',
			name: 'Yousef Haddad',
			source: 'Bayut',
			line: 'in',
			at: '2026-09-29T08:31',
			text: 'Is the 1 bed in Executive Tower still available? Budget around 1.45m.',
			owner_check: "Not on your agency's file",
			priority: 'Normal',
			status: 'waiting',
			agent: 'Priya N.',
			suggested: 'Priya N.',
			reason: 'Covers Business Bay · 4 deals there this year',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'buyer', area: 'Business Bay', beds: 1, budget: 1450000 }
		},
		{
			id: 'IN-37',
			name: 'Hessa Al Mansoori',
			source: 'Website',
			line: 'in',
			at: '2026-09-28T20:10',
			text: '2 bed in Creek Harbour, mortgage, 6 months.',
			owner_check: "Not on your agency's file",
			priority: 'Normal',
			status: 'assigned',
			agent: 'Layla H.',
			suggested: 'Layla H.',
			reason: 'Covers Creek Harbour',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'buyer', area: 'Creek Harbour', beds: 2, budget: 2000000 }
		},
		{
			id: 'IN-38',
			name: '@jvc.renter',
			source: 'Instagram',
			line: 'in',
			at: '2026-09-29T10:08',
			text: 'How much for a 1 bed in JVC?',
			owner_check: "Not on your agency's file",
			priority: 'Low · no budget, no phone',
			status: 'waiting',
			agent: 'Priya N.',
			suggested: 'Priya N.',
			reason: 'Covers JVC',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'tenant', area: 'JVC', beds: 1, budget: null }
		},
		{
			id: 'IN-39',
			name: 'Lena Fischer',
			source: 'Bayut',
			line: 'in',
			at: '2026-09-29T09:58',
			text: 'Looking for a 2 bed in Dubai Marina from December, around 160k a year.',
			owner_check: "Not on your agency's file",
			priority: 'Normal',
			status: 'waiting',
			agent: 'Sara A.',
			suggested: 'Sara A.',
			reason: 'Covers Dubai Marina · speaks English',
			requests: [],
			lead_id: null,
			via_request: false,
			want: { type: 'tenant', area: 'Dubai Marina', beds: 2, budget: 160000 }
		}
	]
}
