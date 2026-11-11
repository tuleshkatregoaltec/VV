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
