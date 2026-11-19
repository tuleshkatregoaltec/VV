<script lang="ts">
import Mic from 'lucide-svelte/icons/mic'
import RotateCcw from 'lucide-svelte/icons/rotate-ccw'
import Send from 'lucide-svelte/icons/send'
import Square from 'lucide-svelte/icons/square'
import { onMount } from 'svelte'
import { chat } from '$lib/api/chat'
import { createVoiceRecorder, liveSubtitles } from './voice.svelte'

/**
 * Pop-up while the agent talks: live subtitles while recording, then the server's text of the
 * complete message to check and edit. Only Send passes it on; any change the assistant proposes
 * still waits on its own card.
 */
let { onsend, onclose }: { onsend: (text: string) => void; onclose: () => void } = $props()

const voice = createVoiceRecorder({ transcribe: chat.transcribe })
let text = $state('')
let subtitleEl: HTMLParagraphElement | undefined = $state()

onMount(() => {
	voice.start()
	return voice.reset
})

$effect(() => {
	if (voice.state === 'review') text = voice.text
})

// Keep the newest words in view as the subtitle grows.
$effect(() => {
	void voice.live
	void voice.interim
	if (subtitleEl) subtitleEl.scrollTop = subtitleEl.scrollHeight
})

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function send() {
	const message = text.trim()
	if (!message) return
	voice.reset()
	onsend(message)
}

function close() {
	voice.reset()
	onclose()
}

function onTextKeydown(e: KeyboardEvent) {
	if (e.key === 'Enter' && !e.shiftKey) {
		e.preventDefault()
		send()
	}
}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && close()} />

<!-- The backdrop does not close the pop-up: a stray click must not throw a recording away. -->
<div class="voice-backdrop" role="presentation">
	<div class="voice-dialog" role="dialog" aria-modal="true" aria-labelledby="voice-title">
		{#if voice.state === 'idle'}
			<div class="head">
				<Mic size={16} />
				<h3 id="voice-title">Starting the microphone…</h3>
			</div>
			<p class="hint">If your browser asks, allow the microphone.</p>
			<div class="actions">
				<button type="button" class="btn ghost" onclick={close}>Cancel</button>
			</div>
		{:else if voice.state === 'recording' || voice.state === 'transcribing'}
			<div class="head">
				{#if voice.state === 'recording'}
					<span class="dot" aria-hidden="true"></span>
					<h3 id="voice-title">Listening…</h3>
					<span class="time">{clock(voice.seconds)} / {clock(voice.maxSeconds)}</span>
				{:else}
					<Mic size={16} />
					<h3 id="voice-title">Getting your words…</h3>
				{/if}
			</div>
			<p
				class={['subtitle', voice.state === 'transcribing' && 'settling']}
				bind:this={subtitleEl}
				aria-live="polite"
			>
				{#if voice.live || voice.interim}
					{voice.live}
					<span class="interim">{voice.interim}</span>
				{:else if voice.state === 'transcribing'}
					<span class="interim">One moment…</span>
				{:else if liveSubtitles}
					<span class="interim">Say what you need, e.g. “Move Ahmed to qualified”.</span>
				{:else}
					<span class="interim">Speak now. Your words will show here when you stop.</span>
				{/if}
			</p>
			<div class="actions">
				<button type="button" class="btn ghost" onclick={close}>Cancel</button>
				<button
					type="button"
					class="btn"
					disabled={voice.state === 'transcribing'}
					onclick={voice.stop}
				>
					<Square size={14} /> Stop
				</button>
			</div>
		{:else if voice.state === 'review'}
			<div class="head">
				<Mic size={16} />
				<h3 id="voice-title">Here’s what you said</h3>
			</div>
			<p class="hint">Edit anything I got wrong. Nothing is sent until you press Send.</p>
			<!-- svelte-ignore a11y_autofocus -->
			<textarea
				aria-label="What you said"
				rows="3"
				autofocus
				bind:value={text}
				onkeydown={onTextKeydown}
			></textarea>
			<div class="actions">
				<button type="button" class="btn ghost" onclick={close}>Discard</button>
				<button type="button" class="btn ghost" onclick={voice.start}>
					<RotateCcw size={14} /> Record again
				</button>
				<button type="button" class="btn" disabled={!text.trim()} onclick={send}>
					<Send size={14} /> Send
				</button>
			</div>
		{:else if voice.state === 'error'}
			<div class="head">
				<Mic size={16} />
				<h3 id="voice-title">Voice input</h3>
			</div>
			<p class="err" role="alert">{voice.error}</p>
			<div class="actions">
				<button type="button" class="btn ghost" onclick={close}>Type instead</button>
				<button type="button" class="btn" onclick={voice.start}>
					<Mic size={14} /> Try again
				</button>
			</div>
		{/if}
	</div>
</div>

<style>
	.voice-backdrop {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 16px;
		background: var(--scrim);
	}
	.voice-dialog {
		width: 100%;
		max-width: 560px;
		background: var(--card);
		color: var(--text);
		border: 1px solid var(--sep);
		border-radius: 12px;
		box-shadow: var(--shadow-lg, 0 16px 40px rgb(0 0 0 / 0.18));
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	h3 {
		margin: 0;
		font-size: 16px;
		font-weight: 600;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--red);
		animation: pulse 1.2s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			opacity: 0.35;
			transform: scale(0.8);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
		}
	}
	.time {
		margin-left: auto;
		color: var(--text2);
		font-size: 13px;
		font-variant-numeric: tabular-nums;
	}
	/* Subtitle: big words, the newest at the bottom; words not yet settled are greyed. */
	.subtitle {
		margin: 0;
		min-height: 96px;
		max-height: 200px;
		overflow-y: auto;
		padding: 14px 16px;
		border-radius: 10px;
		background: var(--sunk);
		font-size: 20px;
		line-height: 1.45;
		text-align: center;
		overflow-wrap: anywhere;
	}
	.interim {
		color: var(--text2);
	}
	/* While the server works, the live preview fades: the reviewed text replaces it. */
	.subtitle.settling {
		opacity: 0.55;
	}
	.hint {
		margin: 0;
		color: var(--text2);
		font-size: 13px;
	}
	textarea {
		resize: none;
		min-height: 72px;
		max-height: 220px;
		field-sizing: content;
		font-size: 16px;
		line-height: 1.45;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		flex-wrap: wrap;
	}
	.actions .btn {
		gap: 6px;
	}
	.err {
		color: var(--red);
		font-size: 14px;
		margin: 0;
	}
</style>
