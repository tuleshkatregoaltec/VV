<script lang="ts">
import Check from 'lucide-svelte/icons/check'
import type { StepState } from '$lib/whatsapp/connect-state'

let { states }: { states: readonly [StepState, StepState, StepState] } = $props()
const labels = ['Connect WhatsApp', 'Choose who to block', 'Turn on replies']
</script>

<ol class="rail" aria-label="Setup steps">
	{#each labels as label, i (label)}
		<li class={states[i]} aria-current={states[i] === 'current' ? 'step' : undefined}>
			<span class="node">
				{#if states[i] === 'done'}<Check size={14} strokeWidth={2.5} aria-hidden="true" />{:else}{i + 1}{/if}
			</span>
			<span class="name">{label}</span>
			{#if states[i] === 'done'}<span class="sr">(done)</span>{/if}
		</li>
	{/each}
</ol>

<style>
.rail { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0; padding: 0; list-style: none; }
li { position: relative; display: flex; align-items: center; gap: 10px; padding-right: 12px; min-width: 0; color: var(--text3); }
li::after { content: ''; position: absolute; left: 0; right: 0; bottom: -9px; height: 2px; background: var(--sep); border-radius: 2px; }
li.done::after { background: var(--green); }
li.current::after { background: var(--accent-fill); }
.node { flex: none; width: 24px; height: 24px; border-radius: 50%; display: inline-grid; place-items: center; font-size: 12px; font-weight: 600; border: 1.5px solid var(--sep-strong); background: var(--card); font-variant-numeric: tabular-nums; }
.done .node { background: var(--green); border-color: var(--green); color: #fff; }
.current .node { border-color: var(--accent-fill); color: var(--text); }
.name { font-size: 13.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.current .name { color: var(--text); font-weight: 600; }
.done .name { color: var(--text2); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 640px) {
	.rail { grid-template-columns: 1fr; gap: 10px; }
	li::after { display: none; }
}
</style>
