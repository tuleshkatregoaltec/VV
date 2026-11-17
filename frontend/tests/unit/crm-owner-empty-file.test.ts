import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { previewOwnerFile } from '$lib/crm/api/backend'

/* An empty owners file is stopped in the preview with one clear line, so nothing is uploaded;
   a file with rows is still ready to import. */
describe('owner file preview of an empty file', () => {
	const EMPTY = 'File is empty, so nothing will be imported.'
	const csv = (text: string) => new File([text], 'owners.csv', { type: 'text/csv' })

	it('stops a 0-byte file', async () => {
		expect((await previewOwnerFile(csv(''))).problem).toBe(EMPTY)
	})

	it('stops a file with headers only', async () => {
		const preview = await previewOwnerFile(csv('NameEn,Mobile,UnitNumber\n'))
		expect(preview.problem).toBe(EMPTY)
		expect(preview.rows).toBe(0)
	})

	it('lets a file with rows through', async () => {
		vi.spyOn(client, 'post').mockRejectedValue(new Error('offline'))
		const preview = await previewOwnerFile(csv('NameEn,Mobile,UnitNumber\nAli,0501234567,101\n'))
		expect(preview.problem).toBeNull()
		expect(preview.rows).toBe(1)
	})
})

/* Before importing, the agent sees which field each column feeds, as the backend will read it. */
describe('owner file preview of the columns', () => {
	const csv = (text: string) => new File([text], 'owners.csv', { type: 'text/csv' })
	afterEach(() => vi.restoreAllMocks())

	it('lines up each header with the field the backend reads it into', async () => {
		vi.spyOn(client, 'post').mockResolvedValue({
			sheets: [
				{
					sheet_name: 'Sheet1',
					rows: 1,
					columns: [
						{ header: 'NAMEEN', field: 'contact_name' },
						{ header: 'Mobile', field: 'phone_primary' },
						{ header: 'Villa Ref', field: null }
					],
					mapped_at_import: true
				}
			]
		})
		const preview = await previewOwnerFile(csv('NameEn,Mobile,Villa Ref\nAli,0501234567,V-1\n'))
		expect(preview.fields).toEqual(['contact_name', 'phone_primary', null])
		expect(preview.readAtImport).toBe(true)
	})

	it('takes the header row the backend reads, even when data rows are fuller than it', async () => {
		// A real export (Marina): the header leaves a column blank that every data row fills, so
		// "the fullest row is the header" would show an owner's row as the column names.
		vi.spyOn(client, 'post').mockResolvedValue({
			sheets: [
				{
					sheet_name: 'Sheet1',
					rows: 2,
					columns: [
						{ header: 'NameEn', field: 'contact_name' },
						{ header: 'UnitNumber', field: 'unit_number' }
					],
					mapped_at_import: false
				}
			]
		})
		const preview = await previewOwnerFile(
			csv('NameEn,UnitNumber,\nAli,101,Ukraine\nSara,102,India\n')
		)
		expect(preview.headers).toEqual(['NameEn', 'UnitNumber'])
		expect(preview.fields).toEqual(['contact_name', 'unit_number'])
		expect(preview.sample).toEqual([
			['Ali', '101'],
			['Sara', '102']
		])
		expect(preview.rows).toBe(2)
	})

	it('still lets the file through when the backend cannot say', async () => {
		vi.spyOn(client, 'post').mockRejectedValue(new Error('offline'))
		const preview = await previewOwnerFile(csv('NameEn,Mobile\nAli,0501234567\n'))
		expect(preview.problem).toBeNull()
		expect(preview.fields).toBeNull()
	})
})
