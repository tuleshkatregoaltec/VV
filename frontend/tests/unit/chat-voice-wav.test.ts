/**
 * Voice recordings upload as 16 kHz mono 16-bit PCM WAV: the server refuses any other format
 * and checks loudness on these samples, so a wrong header or scaling breaks every voice message.
 */
import { describe, expect, it } from 'vitest'
import { encodeWav, WAV_RATE } from '$lib/chat/voice/wav'

async function bytes(blob: Blob) {
	return new DataView(await blob.arrayBuffer())
}
const ascii = (view: DataView, at: number) =>
	String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(at + i)))

describe('encodeWav', () => {
	it('writes the WAV header the server reads', async () => {
		const blob = encodeWav(new Float32Array(160))
		const view = await bytes(blob)
		expect(blob.type).toBe('audio/wav')
		expect(view.byteLength).toBe(44 + 160 * 2)
		expect([ascii(view, 0), ascii(view, 8), ascii(view, 12), ascii(view, 36)]).toEqual([
			'RIFF',
			'WAVE',
			'fmt ',
			'data'
		])
		expect(view.getUint16(20, true)).toBe(1) // PCM
		expect(view.getUint16(22, true)).toBe(1) // mono
		expect(view.getUint32(24, true)).toBe(WAV_RATE)
		expect(view.getUint16(34, true)).toBe(16)
		expect(view.getUint32(40, true)).toBe(160 * 2)
	})

	it('keeps loud samples loud and clips anything past full scale', async () => {
		const view = await bytes(encodeWav(new Float32Array([0, 0.5, -0.5, 1, -1, 2, -2])))
		const samples = [0, 1, 2, 3, 4, 5, 6].map((i) => view.getInt16(44 + i * 2, true))
		expect(samples).toEqual([0, 16383, -16384, 32767, -32768, 32767, -32768])
	})
})
