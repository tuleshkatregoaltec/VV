<script lang="ts">
import X from 'lucide-svelte/icons/x'

/**
 * Guest emails as chips: type an address and press Enter, comma or space (or paste a list).
 * Invalid addresses are kept in the box with a note; Backspace on an empty box removes the last chip.
 */
let {
	id,
	guests = $bindable([]),
	disabled = false
}: { id: string; guests: string[]; disabled?: boolean } = $props()

const EMAIL = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/

let draft = $state('')
let invalid = $state('')

function add(raw: string) {
	const bad: string[] = []
	const next = [...guests]
	for (const part of raw.split(/[\s,;]+/)) {
		const email = part.trim().toLowerCase()
		if (!email) continue
		if (!EMAIL.test(email)) bad.push(part.trim())
		else if (!next.includes(email)) next.push(email)
	}
	guests = next.slice(0, 50)
	draft = bad.join(', ')
	invalid = bad.length ? `Not an email address: ${draft}` : ''
}

function remove(email: string) {
	guests = guests.filter((g) => g !== email)
}

function onkeydown(e: KeyboardEvent) {
	if (['Enter', ',', ';', ' ', 'Tab'].includes(e.key) && draft.trim()) {
		e.preventDefault()
		add(draft)
	} else if (e.key === 'Enter') {
		e.preventDefault()
	} else if (e.key === 'Backspace' && !draft && guests.length) {
		guests = guests.slice(0, -1)
	}
}

function onpaste(e: ClipboardEvent) {
	const text = e.clipboardData?.getData('text') ?? ''
	if (!/[\s,;]/.test(text)) return
	e.preventDefault()
	add(`${draft} ${text}`)
}
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class={['guests', disabled && 'off']} onclick={() => document.getElementById(id)?.focus()}>
	{#each guests as email (email)}
		<span class="guest">
			<span class="avatar" aria-hidden="true">{email[0].toUpperCase()}</span>
			<span class="addr">{email}</span>
			<button type="button" aria-label="Remove {email}" {disabled} onclick={() => remove(email)}>
				<X size={13} />
			</button>
		</span>
	{/each}
	<input
		{id}
		type="email"
		autocomplete="email"
		placeholder={guests.length ? 'Add another guest' : 'Add guests by email'}
		{disabled}
		bind:value={draft}
		{onkeydown}
		{onpaste}
		onblur={() => draft.trim() && add(draft)}
	/>
</div>
{#if invalid}<div class="small bad">{invalid}</div>{/if}

<style>
	.guests {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		min-height: 44px;
		padding: 6px 8px;
		border: 1px solid var(--sep-strong);
		border-radius: 10px;
		background: var(--card);
		cursor: text;
	}
	.guests:focus-within {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--sel);
	}
	.guests.off {
		opacity: 0.55;
	}
	.guest {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		padding: 3px 4px 3px 3px;
		border: 1px solid var(--sep);
		border-radius: 999px;
		background: var(--hover);
		font-size: 13px;
	}
	.avatar {
		display: inline-grid;
		place-items: center;
		width: 22px;
		height: 22px;
		flex: none;
		border-radius: 50%;
		background: var(--accent);
		color: var(--card);
		font-size: 11px;
		font-weight: 700;
	}
	.addr {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.guest button {
		display: inline-grid;
		place-items: center;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		color: var(--text3);
	}
	.guest button:hover {
		background: var(--sep);
		color: var(--text);
	}
	.guests input {
		flex: 1;
		min-width: 160px;
		height: 30px;
		border: 0;
		padding: 0 4px;
		background: transparent;
		color: var(--text);
		box-shadow: none;
		outline: none;
	}
	.bad {
		color: var(--red);
	}
</style>
