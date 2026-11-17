<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Check from 'lucide-svelte/icons/check'
import Upload from 'lucide-svelte/icons/upload'
import Users from 'lucide-svelte/icons/users'
import { crmQueries } from '../../queries'

/**
 * Setup progress for lead routing, each step ticked from real data (organization administrators:
 * the teams list is theirs to read). Teams and people are managed in Organisation settings.
 */
const teams = createQuery(() => crmQueries.teams())
const rules = createQuery(() => crmQueries.routingRules())

const steps = $derived([
	{ done: 'Team created', todo: 'Create a team', ok: (teams.data?.teams.length ?? 0) > 0 },
	{
		done: 'Agents added',
		todo: 'Add agents',
		ok: teams.data?.teams.some((t) => t.members.length > 0) ?? false
	},
	{ done: 'Rules ready', todo: 'Add a rule', ok: rules.data?.some((r) => r.enabled) ?? false }
])
</script>

<section class="setup" aria-label="Setup">
	<b class="lead">Setup</b>
	<ol>
		{#each steps as s, i (s.done)}
			<li class={[s.ok && 'ok']}>
				<span class="dot" aria-hidden="true">{#if s.ok}<Check size={14} strokeWidth={3} />{:else}{i + 1}{/if}</span>
				<span>{s.ok ? s.done : s.todo}</span>
			</li>
		{/each}
	</ol>
	<div class="setup-actions">
		<a class="btn ghost sm" href="/crm/leads"><Upload size={16} /> Import leads</a>
		<a class="btn ghost sm manage" href="/crm/organization?tab=teams"><Users size={16} /> Manage teams &amp; access</a>
	</div>
</section>

<style>
	.setup {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem 1.5rem;
		padding: 0.9rem 1.1rem;
		border: 1px solid var(--routing-border);
		border-radius: 12px;
		background: var(--routing-tint);
	}
	.lead {
		font-size: 16px;
	}
	ol {
		flex: 1;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--text2);
	}
	li + li::before {
		content: '';
		width: 2.5rem;
		height: 1px;
		margin-right: 0.5rem;
		background: var(--sep);
	}
	li.ok {
		color: var(--text);
	}
	.dot {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--sunk);
		font-size: 12px;
		font-weight: 600;
	}
	.ok .dot {
		background: var(--green);
		color: var(--on-btn);
	}
	.setup-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
	}
	.setup-actions a {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		white-space: nowrap;
	}
	.manage {
		border-color: var(--routing-border);
	}
	@media (max-width: 720px) {
		li + li::before {
			display: none;
		}
	}
</style>
