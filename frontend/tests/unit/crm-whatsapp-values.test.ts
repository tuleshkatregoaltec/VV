import { describe, expect, it } from 'vitest'

import { fillValues, variableCount } from '$lib/crm/whatsapp'

describe('WhatsApp opening message values', () => {
	it('asks for one value per {{n}} so Meta never rejects a template for a missing parameter', () => {
		expect(variableCount('Hi {{1}}, this is {{2}} about {{3}}.')).toBe(3)
		expect(variableCount('Hi {{ 2 }} and {{1}}')).toBe(2)
		expect(variableCount('No values here')).toBe(0)
	})

	it('previews exactly what the contact will read, marking values still to fill', () => {
		const body = 'Hi {{1}}, this is {{2}} from Vitevue.'
		expect(fillValues(body, ['Asha', 'Sara'])).toBe('Hi Asha, this is Sara from Vitevue.')
		expect(fillValues(body, ['Asha', '  '])).toBe('Hi Asha, this is … from Vitevue.')
	})
})
