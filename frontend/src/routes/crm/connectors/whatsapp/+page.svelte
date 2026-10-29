<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import { WHATSAPP_DEMO } from '$lib/crm/api/whatsappDemo'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import StageChip from '$lib/crm/components/ui/StageChip.svelte'
import { SOURCES } from '$lib/crm/config'
import { stamp } from '$lib/crm/email'
import { crmQueries } from '$lib/crm/queries'
import { openLead, panel } from '$lib/crm/stores/panel.svelte'
import { chatName, chatSub, potential, windowHoursLeft } from '$lib/crm/whatsapp'
import { errorText } from '$lib/crm/write'

/**
 * Connectors › WhatsApp (Meta WhatsApp Cloud API): chats between agents and their contacts on the
 * business number; a chat opens to read and reply. One shared Vitevue number; an administrator
 * connects it and its opening messages outside the CRM.
 */
const status = createQuery(() => crmQueries.whatsappStatus())
const chats = createQuery(() => crmQueries.whatsappChats())

const facts = $derived(
	status.data
		? status.data.configured
			? `${status.data.business_name ?? 'Business'} · ${status.data.display_number ?? ''}${chats.data ? ` · ${chats.data.length} chats` : ''}`
			: 'Not connected · ask your administrator to connect the business number'
		: ''
)
</script>

<svelte:head><title>WhatsApp · Connectors · CRM Beta</title></svelte:head>

<PageHeader title="WhatsApp" {facts}>
	{#snippet right()}
		{#if WHATSAPP_DEMO}<Chip tone="amber">Sample data</Chip>{/if}
		<a class="btn ghost sm" href="/crm/connectors"><ArrowLeft size={14} /> Connectors</a>
	{/snippet}
</PageHeader>

<div class="filters">
	<span class="sub">
		Chats on the business number. A number that matches no lead needs review before it joins Leads.
	</span>
</div>

{#if chats.data}
	<div class="card">
		<div class="tblwrap">
			<table class="tbl">
				<thead>
					<tr><th>Contact</th><th>Source</th><th>Potential</th><th>Last message</th><th>Reply</th><th>When</th></tr>
				</thead>
				<tbody>
					{#each chats.data as c (c.wa_id)}
						{@const hours = windowHoursLeft(c.window_ends_at)}
						<tr class="row">
							<td>
								<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'whatsapp-chat', waId: c.wa_id })}>
									{chatName(c)}
								</button>
								{#if c.unread}<Chip tone="blue">{c.unread} new</Chip>{/if}
								{#if chatSub(c)}<div class="sub">{chatSub(c)}</div>{/if}
								<div class="wa-lead">
									{#if c.lead_id !== null}
										{#if c.lead_stage}<StageChip stage={c.lead_stage} />{/if}
										<button type="button" class="btn plain sm" onclick={() => c.lead_id && openLead(c.lead_id, 'conversation')}>
											Open lead
										</button>
									{:else}
										<Chip tone="amber">Needs review</Chip>
									{/if}
								</div>
							</td>
							<td data-label="Source">
								{#if c.lead_source}
									<span class="wa-src" style:--c={SOURCES[c.lead_source].color}>{SOURCES[c.lead_source].label}</span>
									{#if c.lead_source_short && c.lead_source_short !== SOURCES[c.lead_source].label}
										<div class="sub">{c.lead_source_short}</div>
									{/if}
								{:else}
									<span class="wa-src">WhatsApp</span>
									<div class="sub">Wrote in, not on a lead yet</div>
								{/if}
							</td>
							<td data-label="Potential">
								{#if c.lead_score !== null}
									{@const p = potential(c.lead_score)}
									<span class={['score', p.band]} title="Lead score">{c.lead_score}%</span>
									<span class="sub">{p.label}</span>
								{:else}<span class="sub">—</span>{/if}
							</td>
							<td data-label="Last message">
								<span class="sub wa-clip">{c.last_direction === 'out' ? 'You: ' : ''}{c.last_body}</span>
							</td>
							<td data-label="Reply">
								{#if hours}<Chip tone="green">Open · {hours}h left</Chip>{:else}<span class="sub">Opening message needed</span>{/if}
							</td>
							<td data-label="When" class="nowrap">{stamp(c.last_at)}</td>
						</tr>
					{:else}
						<tr>
							<td colspan="6">
								<Empty
									text={status.data?.configured
										? 'No chats yet. Start one from a lead’s Conversation tab.'
										: 'No chats yet. Once WhatsApp is connected, chats with your contacts show here.'}
								/>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
	{#if chats.isError}
		<ErrorLine bar message={errorText(chats.error)} onretry={() => chats.refetch()} />
	{/if}
{:else if chats.isError}
	<div class="card"><ErrorLine message={errorText(chats.error)} onretry={() => chats.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={4} /></div>
{/if}
<style>
	.wa-src {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.wa-src::before {
		content: '';
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--c, var(--green));
	}
	.wa-lead {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 4px;
	}
	.wa-clip {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		max-width: 420px;
	}
</style>
