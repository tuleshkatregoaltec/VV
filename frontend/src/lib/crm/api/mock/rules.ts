/**
 * Business rules from docs/crm/business-rules.md. In production these run in FastAPI; the
 * fixture backend runs this copy so the Svelte side only ever renders results. Values marked
 * "proposal" in the docs are implemented as proposed.
 */
import type {
	Chip,
	CommissionAmounts,
	DealType,
	LeadFields,
	LeadStage,
	LeadType,
	Source
} from '../types'

/** "Today" in the sample data (fixtures.json). */
export const TODAY = '2026-09-29'

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const SALE_STAGES = [
	'Offer accepted',
	'Form F signed',
	'Mortgage / bank',
	'NOC',
	'Transfer booked',
	'Transferred'
]
export const RENT_STAGES = ['Contract', 'Deposit and cheques', 'Ejari', 'Keys']
export const SALE_DOCS = [
	'Passport',
	'Emirates ID',
	'Form F',
	'Title deed',
	'NOC',
	"Manager's cheque"
]
export const RENT_DOCS = ['Passport', 'Emirates ID', 'Tenancy contract', 'Cheques']
/** Owner ID is one slot: passport or Emirates ID, whichever the owner has (30 Sep evening). */
export const LISTING_DOCS = ['Form A', 'Title deed', 'Owner ID', 'Photos']
export const LISTING_DOC_NOTES: Record<string, string> = {
	'Owner ID': 'Passport or Emirates ID, whichever the owner has'
}

/** Proposal: documents a lead stage asks for. Optional at the move; they can be added later. */
export const LEAD_STAGE_DOCS: Record<LeadType, Partial<Record<LeadStage, string[]>>> = {
	buyer: {
		qualified: ['Passport', 'Emirates ID'],
		offer: ['Form B', 'Proof of funds or mortgage pre-approval']
	},
	tenant: {
		qualified: ['Passport', 'Emirates ID'],
		offer: ['Residence visa', 'Salary certificate or trade licence']
	},
	seller: { qualified: ['Title deed', 'Owner ID'] },
	landlord: { qualified: ['Title deed', 'Owner ID'] }
}

/**
 * Stages by lead type (6 Oct, 03:40): a seller or landlord is never taken to a viewing. Their
 * stage names are a proposal (Listed replaces Viewing); agencies may rename them (open).
 */
export const LEAD_STAGES: Record<LeadType, LeadStage[]> = {
	buyer: ['new', 'contacted', 'qualified', 'viewing', 'offer', 'won', 'lost'],
	tenant: ['new', 'contacted', 'qualified', 'viewing', 'offer', 'won', 'lost'],
	seller: ['new', 'contacted', 'qualified', 'listed', 'offer', 'won', 'lost'],
	landlord: ['new', 'contacted', 'qualified', 'listed', 'offer', 'won', 'lost']
}

/** DLD Circular 02-2026: no contact with an owner without a documented prior transaction. */
export const GATE_LINE = 'Add a prior deal record before contacting'

export const CONTACT_OUTCOMES = [
	'Spoke to them',
	'No answer',
	'Asked to call back',
	'Replied on WhatsApp'
]
export const LOST_REASONS = [
	'Bought or rented elsewhere',
	'Not ready yet',
	'Budget does not fit',
	'No reply after 3 tries',
	'Not a real enquiry'
]

/** Proposal (decisions.md, open): Matches may go this far over the budget. */
export const MATCH_OVER_BUDGET = 0.1

/** Conveyancing checklist: what each stage needs, in order. `doc` items are document slots. */
type CheckItem = string | { doc: string; label?: string }
export const CONVEYANCING: Record<DealType, { who: string; items: CheckItem[] }[]> = {
	sale: [
		{
			who: 'Buyer, seller and both agents',
			items: [
				'Offer accepted in writing',
				'Form B (buyer) and Form A (seller) signed in the Dubai Brokers app',
				{ doc: 'Passport' },
				{ doc: 'Emirates ID' }
			]
		},
		{
			who: 'Buyer, seller and both agents',
			items: [
				'Form F (MOU) signed by buyer and seller',
				{ doc: 'Form F' },
				'10% security deposit cheque held by the brokerage'
			]
		},
		{
			who: "Buyer's bank and valuer · cash buyers skip this stage",
			items: ['Mortgage pre-approval', 'Bank valuation done', 'Final offer letter from the bank']
		},
		{
			who: 'Developer',
			items: [
				'NOC applied for with the developer (the seller usually pays the fee)',
				{ doc: 'NOC' }
			]
		},
		{
			who: 'Trustee office',
			items: [
				'Transfer appointment booked',
				{
					doc: "Manager's cheque",
					label: "Manager's cheques: seller, DLD fee (4%), trustee fee"
				},
				'Both sides confirmed for the appointment'
			]
		},
		{
			who: 'Dubai Land Department',
			items: [
				"Title deed issued in the buyer's name",
				{ doc: 'Title deed' },
				'DLD transaction number recorded',
				'Commission invoice sent'
			]
		}
	],
	rent: [
		{
			who: 'Tenant, landlord and agent',
			items: [
				'Tenancy contract signed by both sides',
				{ doc: 'Tenancy contract' },
				{ doc: 'Passport' },
				{ doc: 'Emirates ID' }
			]
		},
		{
			who: 'Tenant and landlord',
			items: ['Security deposit received', 'Rent cheques received', { doc: 'Cheques' }]
		},
		{ who: 'Ejari', items: ['Ejari registered', 'Ejari number recorded'] },
		{
			who: 'Tenant and landlord',
			items: ['Move-in inspection done', 'Keys handed over', 'Commission invoice sent']
		}
	]
}

/** Proposal: a forward move into these stages needs these documents on file. */
export const STAGE_GATES: Record<string, string[]> = {
	'Form F signed': ['Form F'],
	'Transfer booked': ['NOC'],
	Transferred: ['Title deed', "Manager's cheque"],
	Ejari: ['Tenancy contract']
}

export function stagesOf(type: DealType): string[] {
	return type === 'sale' ? SALE_STAGES : RENT_STAGES
}

export function docsOf(type: DealType): string[] {
	return type === 'sale' ? SALE_DOCS : RENT_DOCS
}

export function dealTypeOf(type: LeadType): DealType {
	return type === 'buyer' || type === 'seller' ? 'sale' : 'rent'
}

/* ── dates ── */

function parse(date: string): number {
	return Date.parse(`${date}T00:00:00Z`)
}

export function daysFrom(date: string, today = TODAY): number {
	return Math.round((parse(date) - parse(today)) / 864e5)
}

export function addDays(date: string, n: number): string {
	return new Date(parse(date) + n * 864e5).toISOString().slice(0, 10)
}

export function dayLabel(date: string): string {
	const d = new Date(parse(date))
	return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`
}

export function shortDate(date: string): string {
	const d = new Date(parse(date))
	return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`
}

export function mondayOf(date: string): string {
	const dow = new Date(parse(date)).getUTCDay()
	return addDays(date, -((dow + 6) % 7))
}

/** Current Dubai time (UTC+4) as HH:MM, for history rows written now. */
export function nowLabel(): string {
	const d = new Date(Date.now() + 4 * 3600e3)
	return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

/* ── money ── */

export function fmt(n: number): string {
	return Math.round(n).toLocaleString('en-US')
}

export function short(n: number): string {
	return n >= 1e6 ? `${+(n / 1e6).toFixed(2)}m` : fmt(n)
}

/* ── phone numbers ── */

/** `050 123 4567`, `00971…`, `971…`, `+971…` → `+971 50 123 4567`. Null when not a UAE mobile. */
export function normalisePhone(raw: string): string | null {
	const digits = raw.replace(/\D/g, '')
	const local = digits.replace(/^(00971|971|0)/, '')
	if (!/^5\d{8}$/.test(local)) return null
	return `+971 ${local.slice(0, 2)} ${local.slice(2, 5)} ${local.slice(5)}`
}

/* ── score (placeholder until Maan's model) ── */

const SOURCE_WEIGHT: Record<Source, number> = {
	inbound: 15,
	own_contact: 5,
	file: 5,
	agent_to_agent: -15
}

export function moneyStated(fields: LeadFields): boolean {
	return Boolean(fields.budget_aed || fields.target_price_aed || fields.expected_rent_aed)
}

export function scoreLead(source: Source, fields: LeadFields): number {
	return Math.max(0, Math.min(95, 30 + (moneyStated(fields) ? 15 : 0) + SOURCE_WEIGHT[source]))
}

/* ── lead list summary ("Details" column) ── */

export function leadSummary(type: LeadType, fields: LeadFields): { line: string; sub: string } {
	const num = (v: unknown) => (typeof v === 'number' ? v : Number(v) || 0)
	if (type === 'seller') {
		const t = num(fields.target_price_aed)
		return {
			line: String(fields.unit || 'Unit not set'),
			sub: t ? `Target AED ${short(t)}` : 'Target not set'
		}
	}
	if (type === 'landlord') {
		const r = num(fields.expected_rent_aed)
		return {
			line: String(fields.unit || 'Unit not set'),
			sub: r ? `Rent ${fmt(r)} a year` : 'Rent not set'
		}
	}
	const b = num(fields.budget_aed)
	return {
		line: String(fields.wants || 'Not stated'),
		sub: `${type === 'tenant' ? 'Rent' : 'Sale'}${b ? ` · ${short(b)}` : ''}`
	}
}

/* ── commission ── */

export function commission(
	value: number,
	c: { rate_pct: number; cobroker_pct: number; referral_pct: number; agent_pct: number }
): CommissionAmounts {
	const gross = (value * c.rate_pct) / 100
	const afterCo = gross * (1 - c.cobroker_pct / 100)
	const referral = (afterCo * c.referral_pct) / 100
	const net = afterCo - referral
	const agent = (net * c.agent_pct) / 100
	return {
		gross: Math.round(gross),
		cobroker: Math.round(gross - afterCo),
		referral: Math.round(referral),
		net: Math.round(net),
		agent: Math.round(agent),
		agency: Math.round(net - agent),
		vat: Math.round(afterCo * 0.05)
	}
}

export function defaultCommission(type: DealType, source: Source | null) {
	return {
		rate_pct: type === 'sale' ? 2 : 5,
		cobroker_pct: source === 'agent_to_agent' ? 50 : 0,
		referral_pct: 0,
		agent_pct: 50
	}
}

/* ── document name matching (case-insensitive, whole words, first match wins) ── */

/**
 * The name is split on spaces, `_`, `-` and `.` and matched word by word, so `id_front.jpg` is
 * the Emirates ID but `payment amount.pdf` is not Form F and `checklist.pdf` is not a cheque.
 */
export function matchDocument(fileName: string): string | null {
	const words = fileName
		.toLowerCase()
		.split(/[\s_\-.]+/)
		.filter(Boolean)
	const has = (...w: string[]) => words.some((x) => w.includes(x))
	const formF = words.some((x, i) => (x === 'form' && words[i + 1] === 'f') || x === 'formf')
	if (has('passport', 'passports')) return 'Passport'
	if (has('emirates', 'emiratesid', 'eid', 'id')) return 'Emirates ID'
	if (formF || has('mou')) return 'Form F'
	if (has('title', 'deed', 'titledeed')) return 'Title deed'
	if (has('noc')) return 'NOC'
	if (has('tenancy', 'lease', 'contract')) return 'Tenancy contract'
	if (has('cheque', 'cheques', 'check', 'checks')) {
		return words.some((x) => x.startsWith('manager')) ? "Manager's cheque" : 'Cheques'
	}
	return null
}

/* ── listings ── */

/** One rule for Publish and Relist: a permit is valid through its expiry date. */
export function permitValid(permit: { expires: string } | null): boolean {
	return Boolean(permit && daysFrom(permit.expires) >= 0)
}

export function permitStatus(permit: { expires: string } | null): 'none' | 'valid' | 'expired' {
	if (!permit) return 'none'
	return permitValid(permit) ? 'valid' : 'expired'
}

/* ── CSV (import requests) ── */

/** RFC 4180: quoted fields may hold commas, doubled quotes and line breaks. */
export function parseCsv(text: string): string[][] {
	const rows: string[][] = []
	let row: string[] = []
	let field = ''
	let quoted = false
	const src = text.replace(/^﻿/, '')
	for (let i = 0; i < src.length; i++) {
		const c = src[i]
		if (quoted) {
			if (c === '"' && src[i + 1] === '"') {
				field += '"'
				i++
			} else if (c === '"') quoted = false
			else field += c
		} else if (c === '"') quoted = true
		else if (c === ',') {
			row.push(field)
			field = ''
		} else if (c === '\n' || c === '\r') {
			if (c === '\r' && src[i + 1] === '\n') i++
			row.push(field)
			rows.push(row)
			row = []
			field = ''
		} else field += c
	}
	if (field || row.length) {
		row.push(field)
		rows.push(row)
	}
	return rows.map((r) => r.map((f) => f.trim())).filter((r) => r.some((f) => f !== ''))
}

export type ImportColumn = 'name' | 'phone' | 'budget' | 'area'

/** Header names per column. `number` on its own is never the phone ("Unit number"). */
const COLUMN_NAMES: Record<ImportColumn, string[]> = {
	name: ['name', 'full name', 'owner name', 'client name'],
	phone: ['phone', 'mobile', 'phone number', 'mobile number', 'tel', 'telephone'],
	budget: ['budget', 'price'],
	area: ['area', 'community', 'location']
}

/** Whole header names first, then partial ones; each header is used once. */
export function detectColumns(header: string[]): Record<ImportColumn, number> {
	const h = header.map((x) => x.trim().toLowerCase())
	const out = { name: -1, phone: -1, budget: -1, area: -1 } as Record<ImportColumn, number>
	const taken = new Set<number>()
	const keys = Object.keys(COLUMN_NAMES) as ImportColumn[]
	for (const pass of ['exact', 'partial'] as const) {
		for (const k of keys) {
			if (out[k] >= 0) continue
			const i = h.findIndex(
				(x, idx) =>
					!taken.has(idx) &&
					COLUMN_NAMES[k].some((n) =>
						pass === 'exact' ? x === n : new RegExp(`(^|[^a-z])${n}([^a-z]|$)`).test(x)
					)
			)
			if (i >= 0) {
				out[k] = i
				taken.add(i)
			}
		}
	}
	return out
}

/* ── chips and thresholds ── */

export function permitChip(permit: { number: string; expires: string } | null): Chip {
	if (!permit) return { tone: 'neutral', label: 'No permit · not advertised' }
	const n = daysFrom(permit.expires)
	if (n < 0) return { tone: 'red', label: 'Permit expired' }
	if (n <= 14) {
		return {
			tone: n <= 7 ? 'red' : 'amber',
			label: `Permit ${permit.number} · ${n} day${n === 1 ? '' : 's'} left`
		}
	}
	return { tone: 'green', label: `Permit ${permit.number} · to ${shortDate(permit.expires)}` }
}

export function formAChip(expires: string | null): Chip | null {
	if (!expires) return null
	const n = daysFrom(expires)
	return { tone: n <= 7 ? 'red' : 'amber', label: `Form A · ${n} days` }
}

/** The document first, then its expiry: a mandate with no Form A on file is not "On file". */
export function formAStatus(onFile: boolean, expires: string | null): Chip {
	if (!onFile) return { tone: 'red', label: 'Not on file' }
	if (!expires) return { tone: 'green', label: 'On file' }
	return { tone: daysFrom(expires) <= 7 ? 'red' : 'amber', label: `Expires ${dayLabel(expires)}` }
}

/** Last stage → green "Done" · late or today → red · ≤3 days amber · else "in N d". */
export function dueChip(due: string, closed: boolean): Chip {
	if (closed) return { tone: 'green', label: 'Done' }
	const n = daysFrom(due)
	if (n < 0) return { tone: 'red', label: `${-n}d late` }
	if (n === 0) return { tone: 'red', label: 'Today' }
	return { tone: n <= 3 ? 'amber' : 'neutral', label: `in ${n}d` }
}

export function renewalChips(rent: number, median: number, leaseEnd: string) {
	const n = daysFrom(leaseEnd)
	const gap = Math.round((median / rent - 1) * 100)
	return {
		days_left: n,
		gap_pct: gap,
		gap_chip: {
			tone: gap > 5 ? 'amber' : 'neutral',
			label: `${gap >= 0 ? '+' : ''}${gap}%`
		} as Chip,
		end_chip: {
			tone: n <= 30 ? 'red' : n <= 60 ? 'amber' : 'neutral',
			label: `${n} days · ${shortDate(leaseEnd)}`
		} as Chip
	}
}

export function discountChip(pct: number): Chip {
	const p = Math.round(pct)
	if (pct >= 7) return { tone: 'green', label: `${p}% under` }
	if (pct <= -7) return { tone: 'amber', label: `${-p}% over` }
	return { tone: 'neutral', label: 'In line' }
}

export function deadlineChip(date: string): Chip {
	const n = daysFrom(date)
	return { tone: n <= 7 ? 'red' : 'amber', label: `${n}d` }
}

/** "in 41 days · 9 Nov" / "21 days ago · 8 Sep" */
export function eventLabel(date: string): string {
	const n = daysFrom(date)
	return `${n >= 0 ? `in ${n} day${n === 1 ? '' : 's'}` : `${-n} day${n === -1 ? '' : 's'} ago`} · ${shortDate(date)}`
}

/** Owner → lead (business-rules.md): a lease end or event in the window, a vacancy or a recent sale. */
export function ownerActionable(nextEvent: string, nextEventDate: string, tag: string): boolean {
	const n = daysFrom(nextEventDate)
	return (
		(n >= -60 && n <= 90 && /lease|vacant|sold|reprice|handover/i.test(nextEvent)) ||
		/Vacant|Just sold/.test(tag)
	)
}

/** Default lead type when an owner becomes a lead; the agent can change it. */
export function ownerLeadType(nextEvent: string, tag: string): LeadType {
	if (/Just sold/.test(tag)) return 'buyer'
	if (/reprice/i.test(nextEvent)) return 'seller'
	return 'landlord'
}

/** Matches tier 2 and unit events: a unit that is vacant, or whose lease ends in the next 90 days. */
export function unitActionable(status: string, leaseEnd: string | null): boolean {
	if (/vacant/i.test(status)) return true
	if (!leaseEnd) return false
	const n = daysFrom(leaseEnd)
	return n >= 0 && n <= 90
}

/** "N% over budget" chip in Matches, null when within budget. */
export function overBudgetChip(price: number, budget: number | null): Chip | null {
	if (!budget || price <= budget) return null
	return { tone: 'amber', label: `${Math.round((price / budget - 1) * 100)}% over budget` }
}

/** Within the budget plus the allowed margin (or no budget stated). */
export function fitsBudget(price: number, budget: number | null): boolean {
	return !budget || !price || price <= budget * (1 + MATCH_OVER_BUDGET)
}
