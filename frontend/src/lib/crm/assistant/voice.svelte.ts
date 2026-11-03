/**
 * Voice input for the CRM Assistant: record, show live subtitles, then the server's text for the
 * agent to review. Nothing is sent from here; the agent sends the reviewed text like a typed
 * message.
 *
 * The recording is what counts: it is converted to WAV and transcribed by the server. Live
 * subtitles come from the browser's speech recognition where it has one (not Firefox) and are
 * only a preview.
 */
import { ApiError } from '$lib/api/client'
import { toWav } from './wav'

export type VoiceState = 'idle' | 'recording' | 'transcribing' | 'review' | 'error'

// The DOM lib does not type speech recognition everywhere (Safari/Chrome prefix it).
interface Recognition {
	lang: string
	continuous: boolean
	interimResults: boolean
	onresult: ((e: { resultIndex: number; results: ArrayLike<RecognitionResult> }) => void) | null
	onend: (() => void) | null
	start: () => void
	abort: () => void
}
interface RecognitionResult {
	isFinal: boolean
	0: { transcript: string }
}
type RecognitionCtor = new () => Recognition

const Ctor: RecognitionCtor | undefined =
	typeof window === 'undefined'
		? undefined
		: ((window as unknown as { SpeechRecognition?: RecognitionCtor }).SpeechRecognition ??
			(window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition)

export const voiceSupported =
	typeof window !== 'undefined' &&
	Boolean(navigator.mediaDevices?.getUserMedia) &&
	typeof MediaRecorder !== 'undefined'

/** Whether words show while the agent is still talking. */
export const liveSubtitles = Boolean(Ctor)

/** A long ramble is cut off so the review stays readable (the server takes about a minute). */
const MAX_SECONDS = 60

const BLOCKED = 'Microphone access is blocked. Allow it in your browser settings and try again.'
const NO_SPEECH = 'I didn’t catch anything. Try again.'
const LIMIT = 'You have used today’s assistant limit. Try again tomorrow.'
const FAILED = 'Could not turn your voice into text. Try again.'

function micError(e: unknown): string {
	const name = e instanceof DOMException ? e.name : ''
	if (name === 'NotAllowedError' || name === 'SecurityError') return BLOCKED
	if (name === 'NotFoundError') return 'No microphone was found.'
	return 'Could not start the microphone. Try again.'
}

interface VoiceDeps {
	transcribe: (wav: Blob) => Promise<{ text: string }>
}

export function createVoiceRecorder(deps: VoiceDeps) {
	let state = $state<VoiceState>('idle')
	let live = $state('')
	let interim = $state('')
	let text = $state('')
	let seconds = $state(0)
	let error = $state<string | undefined>()

	// Each start is a session; a discarded session's late results are ignored.
	let session = 0
	let stream: MediaStream | null = null
	let recorder: MediaRecorder | null = null
	let rec: Recognition | null = null
	let timer: ReturnType<typeof setInterval> | undefined

	const fail = (message: string) => {
		error = message
		state = 'error'
	}

	function release() {
		clearInterval(timer)
		timer = undefined
		rec?.abort()
		rec = null
		for (const track of stream?.getTracks() ?? []) track.stop()
		stream = null
	}

	function startSubtitles(id: number) {
		if (!Ctor) return
		const r = new Ctor()
		r.lang = navigator.language || 'en-US'
		r.continuous = true
		r.interimResults = true
		r.onresult = (e) => {
			let pending = ''
			for (let i = e.resultIndex; i < e.results.length; i++) {
				const result = e.results[i]
				if (result.isFinal) live = `${live} ${result[0].transcript}`.trim()
				else pending += result[0].transcript
			}
			interim = pending.trim()
		}
		// Browsers end recognition after a pause; keep subtitling while still recording.
		r.onend = () => {
			if (rec === r && id === session && state === 'recording') {
				try {
					r.start()
				} catch {
					rec = null
				}
			}
		}
		rec = r
		try {
			r.start()
		} catch {
			rec = null
		}
	}

	async function finish(id: number, chunks: Blob[], type: string) {
		release()
		if (id !== session) return
		state = 'transcribing'
		try {
			const wav = await toWav(new Blob(chunks, { type }))
			const result = await deps.transcribe(wav)
			if (id !== session) return
			text = result.text.trim()
			if (text) state = 'review'
			else fail(NO_SPEECH)
		} catch (e) {
			if (id !== session) return
			fail(e instanceof ApiError && e.status === 429 ? LIMIT : FAILED)
		}
	}

	async function start() {
		if (state === 'recording' || state === 'transcribing') return
		const id = ++session
		state = 'idle'
		live = ''
		interim = ''
		text = ''
		seconds = 0
		error = undefined
		let mic: MediaStream
		try {
			mic = await navigator.mediaDevices.getUserMedia({ audio: true })
		} catch (e) {
			if (id === session) fail(micError(e))
			return
		}
		if (id !== session) {
			// Closed while the browser was asking for the microphone.
			for (const track of mic.getTracks()) track.stop()
			return
		}
		stream = mic
		const chunks: Blob[] = []
		const r = new MediaRecorder(mic)
		r.ondataavailable = (e) => {
			if (e.data.size) chunks.push(e.data)
		}
		r.onstop = () => void finish(id, chunks, r.mimeType)
		recorder = r
		r.start()
		state = 'recording'
		startSubtitles(id)
		timer = setInterval(() => {
			seconds += 1
			if (seconds >= MAX_SECONDS) stop()
		}, 1000)
	}

	/** Stop recording; the server then turns it into text for review. */
	function stop() {
		if (state === 'recording' && recorder?.state === 'recording') recorder.stop()
	}

	/** Throw the recording (or the text on its way back) away. */
	function reset() {
		session++
		if (recorder?.state === 'recording') recorder.stop()
		recorder = null
		release()
		state = 'idle'
		live = ''
		interim = ''
		text = ''
		error = undefined
	}

	return {
		get state() {
			return state
		},
		/** Live subtitles: settled words, then words still being recognised. */
		get live() {
			return live
		},
		get interim() {
			return interim
		},
		/** The server's text, once in review. */
		get text() {
			return text
		},
		get seconds() {
			return seconds
		},
		get error() {
			return error
		},
		maxSeconds: MAX_SECONDS,
		start,
		stop,
		reset
	}
}
