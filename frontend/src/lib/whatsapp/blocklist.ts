import type { BlockBody } from '$lib/api/whatsapp-connect'

/** The backend takes at most 1000 entries per list. */
export const BLOCK_BATCH = 1000

export function parsePhoneNumbers(text: string): { numbers: string[]; invalid: string[] } {
	const numbers: string[] = []
	const invalid: string[] = []
	for (const raw of text.split(/[\n,;]+/)) {
		const entry = raw.trim()
		if (!entry) continue
		let digits = entry.replace(/\D/g, '')
		if (digits.startsWith('00')) digits = digits.slice(2)
		// Real numbers have 7 to 15 digits; letters mean it was not meant as a number.
		if (/[a-z]/i.test(entry) || digits.length < 7 || digits.length > 15) {
			invalid.push(entry)
		} else if (!numbers.includes(digits)) {
			numbers.push(digits)
		}
	}
	return { numbers, invalid }
}

export function selectionAfterToggle(selected: ReadonlySet<string>, id: string): Set<string> {
	const next = new Set(selected)
	if (!next.delete(id)) next.add(id)
	return next
}

/** Select everything shown, or clear what is shown when it is all selected already. */
export function selectVisible(
	selected: ReadonlySet<string>,
	rows: readonly { id: string }[]
): Set<string> {
	const next = new Set(selected)
	if (rows.length > 0 && rows.every((row) => next.has(row.id))) {
		for (const row of rows) next.delete(row.id)
	} else {
		for (const row of rows) next.add(row.id)
	}
	return next
}

function chunk<T>(items: T[]): T[][] {
	const out: T[][] = []
	for (let i = 0; i < items.length; i += BLOCK_BATCH) out.push(items.slice(i, i + BLOCK_BATCH))
	return out
}

/** Turn a selection plus typed numbers into one or more requests the backend accepts. */
export function buildBlockRequest(input: {
	ids: ReadonlySet<string>
	numbers: string[]
	blocked: boolean
}): BlockBody[] {
	const ids = chunk([...input.ids])
	const numbers = chunk(input.numbers)
	const count = Math.max(ids.length, numbers.length)
	const requests: BlockBody[] = []
	for (let i = 0; i < count; i++) {
		const idPart = ids[i]
		const numberPart = numbers[i]
		requests.push({
			...(idPart ? { contact_ids: idPart } : {}),
			...(numberPart ? { phone_numbers: numberPart } : {}),
			blocked: input.blocked
		})
	}
	return requests
}

export type FileContact = { name: string | null; number: string }

const PHONE_RUN = /(?:\+|00)?\d[\d\s().-]{5,}\d/g
const HAS_PHONE = /\d[\d\s().-]{5,}\d/

/** Digits in international form, or null. Local numbers (one leading 0) take the default code. */
export function normalizeNumber(raw: string, countryCode: string): string | null {
	let digits = raw.replace(/\D/g, '')
	if (raw.trim().startsWith('+')) {
		// already international
	} else if (digits.startsWith('00')) {
		digits = digits.slice(2)
	} else if (digits.startsWith('0')) {
		digits = countryCode + digits.slice(1)
	}
	return digits.length >= 7 && digits.length <= 15 ? digits : null
}

function unfoldVcard(text: string): string[] {
	// vCard lines may continue on the next line when it starts with a space or tab.
	return text.replace(/\r?\n[ \t]/g, '').split(/\r?\n/)
}

function fromVcard(text: string, countryCode: string): FileContact[] {
	const out: FileContact[] = []
	let name: string | null = null
	for (const line of unfoldVcard(text)) {
		const upper = line.toUpperCase()
		if (upper.startsWith('BEGIN:VCARD')) name = null
		else if (upper.startsWith('FN:') || upper.startsWith('FN;')) {
			name = line.slice(line.indexOf(':') + 1).trim() || null
		} else if (upper.startsWith('TEL')) {
			const number = normalizeNumber(line.slice(line.lastIndexOf(':') + 1), countryCode)
			if (number) out.push({ name, number })
		}
	}
	return out
}

function fromTable(text: string, countryCode: string): FileContact[] {
	const out: FileContact[] = []
	for (const line of text.split(/\r?\n/)) {
		const numbers = [...line.matchAll(PHONE_RUN)].map((m) => m[0])
		if (numbers.length === 0) continue
		// The name is the first cell that is not a number, for "Name,Phone" style exports.
		const cells = line.split(/[,;\t]/).map((c) => c.replace(/^"|"$/g, '').trim())
		const name = cells.find((c) => c && /[a-z]/i.test(c) && !HAS_PHONE.test(c)) ?? null
		for (const raw of numbers) {
			const number = normalizeNumber(raw, countryCode)
			if (number) out.push({ name, number })
		}
	}
	return out
}

/** Numbers found in a phone's contacts export (.vcf) or a spreadsheet (.csv/.txt), deduplicated. */
export function extractContactNumbers(text: string, countryCode = '971'): FileContact[] {
	const found = /BEGIN:VCARD/i.test(text)
		? fromVcard(text, countryCode)
		: fromTable(text, countryCode)
	const seen = new Map<string, FileContact>()
	for (const contact of found) {
		const prior = seen.get(contact.number)
		if (!prior || (!prior.name && contact.name)) seen.set(contact.number, contact)
	}
	return [...seen.values()]
}
