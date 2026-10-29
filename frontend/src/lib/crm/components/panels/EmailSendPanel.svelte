<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { EVENT_LABEL, SEND_STATUS, stamp } from '../../email'
import { confirmDeleteSend } from '../../emailActions'
import { crmQueries } from '../../queries'
import { openLead, panel } from '../../stores/panel.svelte'
import Chip from '../ui/Chip.svelte'
import EmailBody from '../ui/EmailBody.svelte'
import Kv from '../ui/Kv.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'

/** Connectors › Email › Tracking: one send, its timestamps, the message and every Brevo event. */
let { id }: { id: number } = $props()

const sends = createQuery(() => crmQueries.emailSends(''))
const s = $derived(sends.data?.items.find((x) => x.id === id))
</script>

{#if s}
	<Panel kicker="Email" title={s.subject} sub={`To ${s.to_name ? `${s.to_name} · ` : ''}${s.to_email}`}>
		{#snippet tags()}
			<Chip tone={SEND_STATUS[s.status].tone}>{SEND_STATUS[s.status].label}</Chip>
			{#if s.opens}<Chip tone="outline">{s.opens} {s.opens === 1 ? 'open' : 'opens'}</Chip>{/if}
			{#if s.clicks}<Chip tone="outline">{s.clicks} {s.clicks === 1 ? 'click' : 'clicks'}</Chip>{/if}
		{/snippet}
		<div class="es">
			{#if s.error}<p class="es-err" role="alert">{s.error}</p>{/if}
			<div class="kv">
				<Kv k="Sent" v={stamp(s.sent_at)} />
				<Kv k="Delivered" v={stamp(s.delivered_at)} />
				<Kv k="First opened" v={stamp(s.opened_at)} />
				<Kv k="First clicked" v={stamp(s.clicked_at)} />
				{#if s.bounced_at}<Kv k="Bounced" v={stamp(s.bounced_at)} />{/if}
			</div>

			<section>
				<div class="lbl">Events</div>
				<div class="list">
					{#each [...s.events].reverse() as e, i (i)}
						<div class="li">
							<span class="when mono small">{stamp(e.at)}</span>
							<span>
								<div class="t">{EVENT_LABEL[e.event] ?? e.event}</div>
								{#if e.link}<div class="d"><a href={e.link} target="_blank" rel="noreferrer">{e.link}</a></div>{/if}
							</span>
							<span></span>
						</div>
					{:else}
						<div class="nomatch">No events yet. Use Sync on Tracking to pull them from Brevo.</div>
					{/each}
				</div>
			</section>

			<div class="es-actions">
				{#if s.enquiry_id !== null}
					<button type="button" class="btn ghost sm" onclick={() => s.enquiry_id && openLead(s.enquiry_id)}>
						Open lead
					</button>
				{/if}
				<button
					type="button"
					class="btn plain sm danger-text"
					onclick={async () => (await confirmDeleteSend(s)) && panel.close()}
				>
					Delete from Tracking
				</button>
			</div>

			<section>
				<div class="lbl">Message</div>
				<div class="es-body"><EmailBody text={s.body} /></div>
			</section>
		</div>
	</Panel>
{:else if sends.isPending || sends.isError}
	<PanelLoading query={sends} kicker="Email" />
{:else}
	<Panel kicker="Email" title="Send not found"><p class="muted">This send is no longer in the list.</p></Panel>
{/if}

<style>
	.es {
		display: grid;
		gap: 14px;
	}
	.es-err {
		margin: 0;
		color: var(--red);
		font-size: 13px;
	}
	.es-body {
		font-size: 13px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--card-2);
		padding: 10px 12px;
		margin-top: 6px;
	}
	.es-actions {
		display: flex;
		gap: 8px;
	}
	.es a {
		overflow-wrap: anywhere;
	}
</style>
