/**
 * Voice recordings go to the server as 16 kHz mono 16-bit WAV: the transcription model takes
 * WAV, not the WebM/MP4 browsers record, and 16 kHz keeps a minute under 2 MB.
 */

export const WAV_RATE = 16_000

/** PCM samples in [-1, 1] as a 16-bit mono WAV file. */
export function encodeWav(samples: Float32Array, rate = WAV_RATE): Blob {
	const view = new DataView(new ArrayBuffer(44 + samples.length * 2))
	const text = (at: number, s: string) => {
		for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i))
	}
	text(0, 'RIFF')
	view.setUint32(4, 36 + samples.length * 2, true)
	text(8, 'WAVE')
	text(12, 'fmt ')
	view.setUint32(16, 16, true) // fmt chunk size
	view.setUint16(20, 1, true) // PCM
	view.setUint16(22, 1, true) // mono
	view.setUint32(24, rate, true)
	view.setUint32(28, rate * 2, true) // bytes per second
	view.setUint16(32, 2, true) // bytes per sample
	view.setUint16(34, 16, true) // bits per sample
	text(36, 'data')
	view.setUint32(40, samples.length * 2, true)
	samples.forEach((s, i) => {
		const clamped = Math.max(-1, Math.min(1, s))
		view.setInt16(44 + i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
	})
	return new Blob([view], { type: 'audio/wav' })
}

/** A browser recording (WebM, MP4…) as 16 kHz mono WAV. */
export async function toWav(recording: Blob): Promise<Blob> {
	const context = new AudioContext()
	let decoded: AudioBuffer
	try {
		decoded = await context.decodeAudioData(await recording.arrayBuffer())
	} finally {
		void context.close()
	}
	// A one-channel offline context mixes stereo down and resamples to 16 kHz.
	const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * WAV_RATE), WAV_RATE)
	const source = offline.createBufferSource()
	source.buffer = decoded
	source.connect(offline.destination)
	source.start()
	const rendered = await offline.startRendering()
	return encodeWav(rendered.getChannelData(0))
}
