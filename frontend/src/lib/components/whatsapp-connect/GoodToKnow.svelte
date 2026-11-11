<script lang="ts">
import ChevronDown from 'lucide-svelte/icons/chevron-down'
import { WHATSAPP_MANAGER_URL } from '$lib/whatsapp/connect-state'

// Reassurance for the careful reader, folded away so it does not compete with the next step.
// Once connected, the status section carries the payment reminder, so it is not repeated here.
let { connected = false }: { connected?: boolean } = $props()
</script>

<details class="know">
	<summary><span>Good to know</span><ChevronDown size={16} aria-hidden="true" /></summary>
	<ul>
		<li><b>Keep using WhatsApp on your phone</b> exactly as you do now. Vitevue answers property enquiries alongside you.</li>
		<li><b>Blocked contacts are never read</b> by Vitevue. You choose them in your contacts list.</li>
		<li><b>Personal messages are never stored.</b></li>
		<li><b>You stay in charge of the deal.</b> Offers, negotiation, payments and viewings are handed back to you.</li>
		{#if !connected}
			<li>
				<b>Add a payment method in Meta’s WhatsApp Manager.</b> Meta includes 1,000 free replies a month. After that, replies are billed to your own WhatsApp account by Meta, not by Vitevue.
				<a href={WHATSAPP_MANAGER_URL} target="_blank" rel="noopener noreferrer">Open WhatsApp Manager</a>
			</li>
		{/if}
	</ul>
</details>

<style>
.know { border: 1px solid var(--sep); border-radius: var(--radius-lg); background: var(--card); }
summary { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 12px 16px; font-size: 13.5px; font-weight: 500; color: var(--text2); cursor: pointer; list-style: none; border-radius: var(--radius-lg); }
summary::-webkit-details-marker { display: none; }
summary:hover { color: var(--text); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
summary :global(svg) { transition: transform var(--duration-fast); }
.know[open] summary :global(svg) { transform: rotate(180deg); }
ul { margin: 0; padding: 0 16px 14px; list-style: none; display: grid; gap: 10px; }
li { font-size: 13.5px; line-height: 1.5; color: var(--text2); padding-left: 14px; position: relative; }
li::before { content: ''; position: absolute; left: 0; top: .6em; width: 5px; height: 5px; border-radius: 50%; background: var(--sep-strong); }
li b { color: var(--text); font-weight: 600; }
a { color: var(--accent); font-weight: 500; white-space: nowrap; }
a:hover { text-decoration: underline; }
@media (prefers-reduced-motion: reduce) { summary :global(svg) { transition: none; } }
</style>
