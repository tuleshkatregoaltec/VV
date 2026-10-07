<script lang="ts">
import Save from 'lucide-svelte/icons/save'
import { toast } from '../stores/toast.svelte'
import { EXAMPLE_LEADS, market, type Saved } from './state.svelte'

/** "Save … to a lead": an in-page menu of leads (never a native select, v2 call 6 Oct 04:25). */
let {
	kind,
	label,
	disabled = false,
	primary = false
}: { kind: Saved['kind']; label: string; disabled?: boolean; primary?: boolean } = $props()

let open = $state(false)

function pick(lead: string) {
	open = false
	const item = market.save(kind, label, lead)
	toast.show(`${kind} saved to ${lead} · ${label}`, { undo: () => market.unsave(item.id) })
}
</script>

<span class="mk-pick">
	<button
		type="button"
		class={['btn', !primary && 'ghost sm']}
		aria-haspopup="menu"
		aria-expanded={open}
		{disabled}
		onclick={() => (open = !open)}
	>
		<Save size={15} aria-hidden="true" />Save {kind.toLowerCase()} to a lead
	</button>
	{#if open}
		<div class="mk-menu" role="menu" aria-label="Save to a lead">
			<div class="mk-menu-h">Save {kind.toLowerCase()} to a lead</div>
			{#each EXAMPLE_LEADS as l (l.id)}
				<button type="button" class="mk-mi" role="menuitem" onclick={() => pick(l.name)}>
					<b>{l.name}</b> <span class="muted">· {l.type} · {l.area}</span>
				</button>
			{/each}
		</div>
	{/if}
</span>
<svelte:window onkeydown={(e) => e.key === 'Escape' && (open = false)} />
