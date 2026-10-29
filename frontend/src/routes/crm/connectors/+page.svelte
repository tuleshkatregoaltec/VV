<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowRight from 'lucide-svelte/icons/arrow-right'
import CalendarSync from 'lucide-svelte/icons/calendar-sync'
import Mail from 'lucide-svelte/icons/mail'
import MessageCircle from 'lucide-svelte/icons/message-circle'
import type { ConnectorKind, ConnectorStatus, Tone } from '$lib/crm/api/types'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import { crmQueries } from '$lib/crm/queries'
import { errorText } from '$lib/crm/write'

/**
 * Manager › Connectors (spec 2026-10-28): a gateway, not a settings page. Email opens its Brevo
 * pipeline directly (Brevo is configured on the server, never shown here); WhatsApp is next.
 */
const connectors = createQuery(() => crmQueries.connectors())

const ICON: Record<ConnectorKind, typeof Mail> = {
	email: Mail,
	calendar: CalendarSync,
	whatsapp: MessageCircle
}
const STATUS: Record<ConnectorStatus, { label: string; tone: Tone } | null> = {
	ready: { label: 'Ready', tone: 'green' },
	available: null,
	coming_soon: { label: 'Coming soon', tone: 'outline' }
}

const list = $derived(connectors.data ?? [])
const ready = $derived(list.filter((c) => c.status === 'ready').length)
</script>

<svelte:head><title>Connectors · CRM Beta</title></svelte:head>

<PageHeader
	title="Connectors"
	facts={connectors.data ? `${ready} of ${list.length} ready · leads and message history from each channel` : ''}
/>

{#if connectors.data}
	<div class="cx-grid">
		{#each list as c (c.kind)}
			{@const Icon = ICON[c.kind]}
			{@const s = STATUS[c.status]}
			<svelte:element
				this={c.href ? 'a' : 'section'}
				href={c.href ?? undefined}
				class={['card', 'cx', c.href && 'cx-link', !c.href && 'soon']}
				aria-labelledby="cx-{c.kind}"
			>
				<div class="ch">
					<h2 id="cx-{c.kind}">
						<span class="cx-ic" aria-hidden="true"><Icon size={16} /></span>
						<span class="cx-name">{c.name}</span>
						<span class="facts">{c.provider}</span>
					</h2>
					{#if s}<Chip tone={s.tone}>{s.label}</Chip>{/if}
				</div>
				<div class="cb cx-body">
					<p class="d">{c.line}</p>
					{#if c.href}
						<span class="cx-open">Open {c.name.toLowerCase()} <ArrowRight size={14} /></span>
					{/if}
				</div>
			</svelte:element>
		{/each}
	</div>
	{#if connectors.isError}
		<ErrorLine bar message={errorText(connectors.error)} onretry={() => connectors.refetch()} />
	{/if}
{:else if connectors.isError}
	<div class="card"><ErrorLine message={errorText(connectors.error)} onretry={() => connectors.refetch()} /></div>
{:else}
	<div class="cx-grid">
		{#each [1, 2] as i (i)}<div class="card"><Skeleton rows={3} /></div>{/each}
	</div>
{/if}

<style>
	.cx-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
		gap: 14px;
		align-items: start;
	}
	.cx {
		display: block;
		color: inherit;
		text-decoration: none;
	}
	.cx-link {
		transition: border-color 0.15s;
	}
	.cx-link:hover {
		border-color: var(--sep-strong);
	}
	.cx-link:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}
	.cx .ch {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.cx h2 {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}
	/* The chip stays on the title line: the provider name gives way instead. */
	.cx h2 .facts {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.cx-name {
		white-space: nowrap;
	}
	.cx .ch :global(.chip) {
		flex: none;
	}
	.cx-ic {
		display: inline-grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: 8px;
		background: var(--card-2);
		border: 1px solid var(--line);
		flex: none;
	}
	.cx-body {
		display: grid;
		gap: 10px;
	}
	.cx-body .d,
	.cx-body p {
		margin: 0;
	}
	.cx-body .d {
		font-size: 13px;
		color: var(--text2);
	}
	.cx-open {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 13px;
		font-weight: 600;
		color: var(--blue);
	}
	.cx.soon .cx-ic {
		opacity: 0.6;
	}
</style>
