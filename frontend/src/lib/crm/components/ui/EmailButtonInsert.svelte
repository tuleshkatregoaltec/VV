<script lang="ts">
import MousePointerClick from 'lucide-svelte/icons/mouse-pointer-click'

/**
 * "Add a button" for an email message: a label and a web address become
 * [button: Label](https://…), which the email shows as a button. Clicks are tracked by Brevo.
 */
let { oninsert }: { oninsert: (snippet: string) => void } = $props()

let open = $state(false)
let label = $state('')
let url = $state('')

const valid = $derived(label.trim().length > 0 && /^https?:\/\/\S+\.\S+/.test(url.trim()))

function insert() {
	if (!valid) return
	oninsert(`[button: ${label.trim().replace(/[[\]]/g, '')}](${url.trim()})`)
	label = ''
	url = ''
	open = false
}
</script>

{#if open}
	<div class="ebi">
		<div class="ebi-row">
			<input aria-label="Button text" placeholder="Button text, e.g. Book a viewing" bind:value={label} />
			<input aria-label="Button link" type="url" placeholder="https://…" bind:value={url} />
		</div>
		<div class="ebi-row">
			<button type="button" class="btn sm" disabled={!valid} onclick={insert}>Insert button</button>
			<button type="button" class="btn plain sm" onclick={() => (open = false)}>Cancel</button>
			<span class="small muted">Clicks show on Tracking.</span>
		</div>
	</div>
{:else}
	<button type="button" class="btn ghost sm ebi-open" onclick={() => (open = true)}>
		<MousePointerClick size={14} /> Add a button
	</button>
{/if}

<style>
	.ebi {
		display: grid;
		gap: 6px;
		padding: 8px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--card-2);
	}
	.ebi-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.ebi-row input {
		flex: 1 1 180px;
		min-width: 0;
	}
	.ebi-open {
		justify-self: start;
	}
</style>
