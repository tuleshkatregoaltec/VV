import { afterEach, expect, it, vi } from 'vitest'
import { createVoiceRecorder } from '$lib/crm/assistant/voice.svelte'

class Recorder {
	static all: Recorder[] = []
	state = 'inactive'
	mimeType = 'audio/webm'
	onstop: (() => void) | null = null
	ondataavailable: ((event: { data: Blob }) => void) | null = null
	constructor(_mic: unknown) {
		Recorder.all.push(this)
	}
	start() {
		this.state = 'recording'
	}
	stop() {
		this.state = 'inactive'
	}
}

afterEach(() => {
	vi.unstubAllGlobals()
	vi.useRealTimers()
	Recorder.all = []
})

it('discarded recorder callbacks cannot stop a newly opened microphone or its timer', async () => {
	vi.useFakeTimers()
	const oldStop = vi.fn()
	const newStop = vi.fn()
	const getUserMedia = vi
		.fn()
		.mockResolvedValueOnce({ getTracks: () => [{ stop: oldStop }] })
		.mockResolvedValueOnce({ getTracks: () => [{ stop: newStop }] })
	vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
	vi.stubGlobal('MediaRecorder', Recorder)
	const transcribe = vi.fn()
	const voice = createVoiceRecorder({ transcribe })
	await voice.start()
	voice.reset()
	await voice.start()
	Recorder.all[0].onstop?.()
	await vi.advanceTimersByTimeAsync(1000)
	expect(voice.state).toBe('recording')
	expect(voice.seconds).toBe(1)
	expect(oldStop).toHaveBeenCalledOnce()
	expect(newStop).not.toHaveBeenCalled()
	expect(transcribe).not.toHaveBeenCalled()
	voice.reset()
})
