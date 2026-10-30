<script lang="ts">
import ChartNoAxesColumn from 'lucide-svelte/icons/chart-no-axes-column'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'

/**
 * Manager view placeholder. Its settings (lead handout, agents, reports) have no backend yet, so
 * the page explains what is coming instead of loading data that always fails.
 */
const COMING = [
	{ title: 'Lead handout', line: 'Choose how a waiting enquiry gets an agent.' },
	{ title: 'Agents', line: 'See each agent’s leads, replies and follow-ups.' },
	{ title: 'Reports', line: 'Pipeline and response times across the team.' }
]
</script>

<svelte:head><title>Manager view · CRM Beta</title></svelte:head>

<PageHeader title="Manager view" />

<section class="card soon" aria-labelledby="soon-h">
	<span class="mark" aria-hidden="true"><ChartNoAxesColumn size={22} /></span>
	<h2 id="soon-h">Manager view is coming soon</h2>
	<p>Team settings and reports will live here. Nothing to set up yet.</p>
	<ul>
		{#each COMING as c (c.title)}
			<li><b>{c.title}</b><span>{c.line}</span></li>
		{/each}
	</ul>
</section>

<style>
	.soon {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding: 48px 24px;
	}
	.mark {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 12px;
		background: var(--sunk);
		color: var(--text2);
		margin-bottom: 14px;
	}
	h2 {
		margin: 0;
		font-size: 17px;
		font-weight: 600;
		color: var(--text);
	}
	p {
		margin: 6px 0 22px;
		color: var(--text2);
		font-size: 14px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
		width: 100%;
		max-width: 760px;
	}
	li {
		display: flex;
		flex-direction: column;
		gap: 4px;
		text-align: left;
		padding: 14px;
		border: 1px solid var(--sep);
		border-radius: 10px;
		font-size: 13.5px;
		color: var(--text);
	}
	li span {
		color: var(--text2);
	}
	@media (max-width: 720px) {
		ul {
			grid-template-columns: 1fr;
		}
	}
</style>
