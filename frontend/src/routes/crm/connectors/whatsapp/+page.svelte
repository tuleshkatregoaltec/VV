<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { env } from '$env/dynamic/public'
import { get_access_token } from '$lib/api/auth'
import { WHATSAPP_DEMO } from '$lib/crm/api/whatsappDemo'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import StageChip from '$lib/crm/components/ui/StageChip.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import WhatsAppCampaignInbox from '$lib/crm/components/whatsapp/WhatsAppCampaignInbox.svelte'
import WhatsAppCampaigns from '$lib/crm/components/whatsapp/WhatsAppCampaigns.svelte'
import WhatsAppNumbers from '$lib/crm/components/whatsapp/WhatsAppNumbers.svelte'
import { SOURCES } from '$lib/crm/config'
import { stamp } from '$lib/crm/email'
import { crmQueries } from '$lib/crm/queries'
import { openLead, panel } from '$lib/crm/stores/panel.svelte'
import { chatName, chatSub, potential, windowHoursLeft } from '$lib/crm/whatsapp'
import { connectWhatsAppLive, liveUrl, showsChat } from '$lib/crm/whatsappLive'
import { errorText } from '$lib/crm/write'

/**
 * Connectors › WhatsApp (Meta WhatsApp Cloud API): the signed-in agent's chats on their own
 * number; a chat opens to read and reply. Each agent has a number, so a contact sees a separate
 * chat per agent; an administrator registers the numbers and opening messages.
 */
const status = createQuery(() => crmQueries.whatsappStatus())
const chats = createQuery(() => crmQueries.whatsappChats())
const me = createQuery(() => crmQueries.me())

/* New messages and delivery statuses arrive without a reload while this page is open. */
const queryClient = useQueryClient()
$effect(() => {
	if (WHATSAPP_DEMO || !env.PUBLIC_API_BASE_URL) return
	return connectWhatsAppLive({
		url: liveUrl(env.PUBLIC_API_BASE_URL),
		token: get_access_token,
		onchange: (waId) =>
			queryClient.invalidateQueries({ predicate: (q) => showsChat(q.queryKey, waId) })
	})
})

/* Numbers, campaigns and campaign replies are the organization owner's. */
type Tab = 'chats' | 'campaigns' | 'inbox' | 'numbers'
const owner = $derived(me.data?.is_owner === true)
const tab = $derived<Tab>(
	owner
		? ((['campaigns', 'inbox', 'numbers'] as const).find(
				(t) => t === page.url.searchParams.get('tab')
			) ?? 'chats')
		: 'chats'
)
function selectTab(id: Tab) {
	const url = new URL(page.url)
	if (id === 'chats') url.searchParams.delete('tab')
	else url.searchParams.set('tab', id)
	goto(url, { replaceState: true, noScroll: true, keepFocus: true })
}

const facts = $derived(
	status.data
		? status.data.configured
			? `${status.data.business_name ?? 'Business'} · ${status.data.display_number ?? ''}${chats.data ? ` · ${chats.data.length} chats` : ''}`
			: status.data.connected
				? owner
					? 'Connected · you have no number yet: assign one under Numbers'
					: 'Connected · ask your administrator to assign you a WhatsApp number'
				: 'Not connected · WhatsApp is not set up on the server yet'
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

{#if owner}
	<Tabs
		label="WhatsApp"
		items={[
			{ id: 'chats', label: 'My chats', count: chats.data?.length ?? null },
			{ id: 'campaigns', label: 'Campaigns', count: null },
			{ id: 'inbox', label: 'Campaign inbox', count: null },
			{ id: 'numbers', label: 'Numbers', count: null }
		]}
		value={tab}
		onselect={selectTab}
	/>
{/if}

{#if tab === 'campaigns'}
	<WhatsAppCampaigns />
{:else if tab === 'inbox'}
	<WhatsAppCampaignInbox />
{:else if tab === 'numbers'}
	<WhatsAppNumbers connected={status.data?.connected ?? false} />
{:else}
	<div class="filters">
		<span class="sub">
			Chats on your WhatsApp number. A number that matches no lead needs review before it joins Leads.
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
