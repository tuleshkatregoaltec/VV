<script lang="ts">
import MessageCircle from 'lucide-svelte/icons/message-circle'
import TriangleAlert from 'lucide-svelte/icons/triangle-alert'
import type { AgentConnectionStatus, SignupConfig } from '$lib/api/whatsapp-connect'
import type { ConnectPhase } from '$lib/whatsapp/connect-state'

let {
	config,
	configError = '',
	sdkReady,
	sdkError = '',
	phase,
	error = '',
	previous = null,
	onconnect,
	oncancel,
	onretry
}: {
	config: SignupConfig | undefined
	configError?: string
	sdkReady: boolean
	sdkError?: string
	phase: ConnectPhase
	error?: string
	previous?: AgentConnectionStatus | null
	onconnect: () => void
	oncancel: () => void
	onretry: () => void
} = $props()

const notReady = $derived(config !== undefined && !config.configured)
const busy = $derived(phase !== 'idle')
const label = $derived(
	phase === 'completing'
		? 'Connecting your number…'
		: phase === 'waiting'
			? 'Waiting for Meta…'
			: previous?.state === 'disconnected'
				? 'Connect WhatsApp again'
				: 'Connect WhatsApp'
)
</script>

<section class="card" aria-labelledby="connect-h">
	<div class="ch">
		<h2 id="connect-h">Connect your WhatsApp</h2>
		{#if phase === 'completing'}<span class="chip blue">Finishing</span>{/if}
	</div>
	<div class="cb body">
		{#if previous?.state === 'disconnected'}
			<p class="note">
				WhatsApp was disconnected{previous.disconnected_at ? ` on ${new Date(previous.disconnected_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}` : ''}. Vitevue deleted the contacts it had synced. Your chats are still on your phone.
			</p>
		{/if}
		<p class="lead">
			Buyers message your own WhatsApp number. Vitevue answers their property enquiries from it, so no lead waits for a reply.
		</p>

		<div class="prep">
			<h3>Before you start</h3>
			<ul>
				<li><b>Use the WhatsApp Business app.</b> Personal WhatsApp can’t be connected. Switching is free and keeps all your chats.</li>
				<li><b>Update WhatsApp Business</b> on your phone to the latest version.</li>
				<li><b>Keep your phone nearby.</b> Meta will ask you to confirm the connection there.</li>
			</ul>
		</div>

		{#if notReady}
			<div class="state calm" role="status">
				<MessageCircle size={18} aria-hidden="true" />
				<div>
					<b>WhatsApp connection is being set up</b>
					<span>Check back soon. You can switch to the WhatsApp Business app in the meantime.</span>
				</div>
			</div>
		{:else if configError}
			<div class="state bad" role="alert">
				<TriangleAlert size={18} aria-hidden="true" />
				<div><b>Could not load the connection set-up</b><span>{configError}</span></div>
				<button type="button" class="btn ghost sm" onclick={onretry}>Retry</button>
			</div>
		{:else}
			{#if error}
				<div class="state bad" role="alert">
					<TriangleAlert size={18} aria-hidden="true" />
					<div><b>Not connected yet</b><span>{error}</span></div>
				</div>
			{/if}
			{#if sdkError}
				<div class="state bad" role="alert">
					<TriangleAlert size={18} aria-hidden="true" />
					<div><b>Meta’s sign-in could not load</b><span>{sdkError} An ad blocker can cause this.</span></div>
					<button type="button" class="btn ghost sm" onclick={onretry}>Retry</button>
				</div>
			{/if}
			<div class="go">
				<button
					type="button"
					class="btn go-btn"
					disabled={busy || !sdkReady || config === undefined || !config.state}
					onclick={onconnect}
				>
					<MessageCircle size={16} aria-hidden="true" />{label}
				</button>
				{#if phase === 'waiting'}
					<button type="button" class="btn plain" onclick={oncancel}>Cancel</button>
				{/if}
			</div>
			{#if phase === 'waiting'}
				<p class="hint" role="status">Finish in the Meta window. If it did not open, allow pop-ups for this site and try again.</p>
			{:else}
				<p class="hint">A window from Meta opens. Sign in with Facebook, choose your WhatsApp Business number and confirm on your phone. Vitevue never sees your Facebook password.</p>
			{/if}
		{/if}
	</div>
</section>

<style>
.body { display: grid; gap: 18px; padding: 18px; }
.lead { margin: 0; font-size: 15.5px; line-height: 1.55; color: var(--text); max-width: 56ch; }
.note { margin: 0; font-size: 13.5px; color: var(--text2); background: var(--sunk); border-radius: 8px; padding: 10px 12px; }
.prep h3 { margin: 0 0 8px; font-size: 12px; font-family: var(--font-mono); font-weight: 400; letter-spacing: .08em; text-transform: uppercase; color: var(--text3); }
.prep ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.prep li { position: relative; padding-left: 18px; font-size: 14px; line-height: 1.5; color: var(--text2); }
.prep li::before { content: ''; position: absolute; left: 2px; top: .62em; width: 6px; height: 6px; border-radius: 50%; background: var(--accent-fill); }
.prep b { color: var(--text); font-weight: 600; }
.go { display: flex; gap: 8px; flex-wrap: wrap; }
.go-btn { height: 40px; padding: 0 18px; font-size: 15px; }
.hint { margin: -6px 0 0; font-size: 12.5px; color: var(--text3); max-width: 60ch; line-height: 1.5; }
.state { display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border-radius: 8px; font-size: 13.5px; }
.state > div { display: grid; gap: 2px; flex: 1; min-width: 0; }
.state b { font-weight: 600; }
.state span { color: var(--text2); }
.state :global(svg) { flex: none; margin-top: 2px; }
.calm { background: var(--blue-bg); color: var(--blue); }
.calm span { color: var(--text2); }
.bad { background: var(--red-bg); color: var(--red); }
.bad span { color: var(--text); }
</style>
