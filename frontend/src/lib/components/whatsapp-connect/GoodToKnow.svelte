<script lang="ts">
import CreditCard from 'lucide-svelte/icons/credit-card'
import EyeOff from 'lucide-svelte/icons/eye-off'
import HandHelping from 'lucide-svelte/icons/hand-helping'
import LockKeyhole from 'lucide-svelte/icons/lock-keyhole'
import Smartphone from 'lucide-svelte/icons/smartphone'
import { WHATSAPP_MANAGER_URL } from '$lib/whatsapp/connect-state'

// Once connected, the status card carries the payment reminder, so it is not repeated here.
let { connected = false }: { connected?: boolean } = $props()
</script>

<section class="card know" aria-labelledby="know-h">
	<div class="ch"><h2 id="know-h">Good to know</h2></div>
	<ul class="cb">
		<li>
			<Smartphone size={16} aria-hidden="true" />
			<p><b>Keep using WhatsApp on your phone</b> exactly as you do now. Vitevue answers property enquiries alongside you.</p>
		</li>
		<li>
			<EyeOff size={16} aria-hidden="true" />
			<p><b>Blocked contacts are never read</b> by Vitevue. You choose them in step 2.</p>
		</li>
		<li>
			<LockKeyhole size={16} aria-hidden="true" />
			<p><b>Personal messages are never stored.</b></p>
		</li>
		<li>
			<HandHelping size={16} aria-hidden="true" />
			<p><b>You stay in charge of the deal.</b> Offers, negotiation, payments and viewings are handed back to you.</p>
		</li>
		{#if !connected}
		<li>
			<CreditCard size={16} aria-hidden="true" />
			<p>
				<b>Add a payment method in Meta’s WhatsApp Manager.</b> Meta includes 1,000 free replies a month. After that, replies are billed to your own WhatsApp account by Meta, not by Vitevue.
				<a href={WHATSAPP_MANAGER_URL} target="_blank" rel="noopener noreferrer">Open WhatsApp Manager</a>
			</p>
		</li>
		{/if}
	</ul>
</section>

<style>
.know .cb { list-style: none; margin: 0; display: grid; gap: 14px; }
li { display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: 10px; align-items: start; color: var(--text2); }
li :global(svg) { margin-top: 3px; color: var(--text3); }
p { margin: 0; font-size: 13.5px; line-height: 1.5; }
p b { color: var(--text); font-weight: 600; }
a { color: var(--accent); font-weight: 500; white-space: nowrap; }
a:hover { text-decoration: underline; }
</style>
