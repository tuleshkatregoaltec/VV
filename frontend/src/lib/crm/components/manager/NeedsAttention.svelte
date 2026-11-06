<script lang="ts">
import Empty from '$lib/crm/components/ui/Empty.svelte'
import StageChip from '$lib/crm/components/ui/StageChip.svelte'
import { ago, type MgrData, MOCK_NOW, needsAttention, type ViewAs } from '$lib/crm/mock/manager'
import PrivacyTag from './PrivacyTag.svelte'

/**
 * What needs a manager today: enquiries nobody owns, leads waiting over 24h for a first reply,
 * agents behind on follow-ups. Agent view keeps only their own waiting leads and overdue count.
 */
let { data, view, onopen }: { data: MgrData; view: ViewAs; onopen?: (agentId: number) => void } =
	$props()

const a = $derived(needsAttention(data))
const agentName = $derived(new Map(data.agents.map((x) => [x.id, x.name])))
const hoursWaiting = (iso: string) =>
	Math.floor((Date.parse(MOCK_NOW) - Date.parse(iso)) / 3_600_000)
const myOverdue = $derived(data.agents[0]?.overdueFollowUps ?? 0)
</script>

<section class="card" aria-labelledby="na-h">
	<div class="ch">
		<h2 id="na-h">Needs attention</h2>
	</div>
	<div class={['cols', view === 'agent' && 'one']}>
		{#if view === 'manager'}
			<div class="col">
				<h3>No agent yet <span class="ct">· {a.unassigned.length}</span> <PrivacyTag k="otherLeads" {view} /></h3>
				<div class="list">
					{#each a.unassigned as l (l.id)}
						<div class="li">
							<StageChip stage={l.stage} />
							<div class="min-w-0">
								<div class="t">{l.name}</div>
								<div class="d">{l.source}</div>
							</div>
							<span class="d">{ago(l.createdAt)}</span>
						</div>
					{:else}
						<Empty text="Every enquiry has an agent." />
					{/each}
				</div>
			</div>
		{/if}

		<div class="col">
			<h3>
				{view === 'manager' ? 'Waiting over 24h' : 'Your leads waiting over 24h'}
				<span class="ct">· {a.waiting.length}</span>
			</h3>
			<div class="list">
				{#each a.waiting as l (l.id)}
					<div class="li">
						<StageChip stage={l.stage} />
						<div class="min-w-0">
							<div class="t">{l.name}</div>
							<div class="d">
								{view === 'manager' ? (agentName.get(l.agentId ?? -1) ?? '') : l.source} · no reply yet
							</div>
						</div>
						<span class="wait">{hoursWaiting(l.createdAt)} h</span>
					</div>
				{:else}
					<Empty text="No lead is waiting over a day." />
				{/each}
			</div>
		</div>

		<div class="col">
			<h3>
				Overdue follow-ups
				<span class="ct">· {view === 'manager' ? a.overdueAgents.length : myOverdue}</span>
			</h3>
			<div class="list">
				{#if view === 'manager'}
					{#each a.overdueAgents as x (x.id)}
						<button type="button" class="li" onclick={() => onopen?.(x.id)}>
							<span class="av" aria-hidden="true">{x.initials}</span>
							<span class="t">{x.name}</span>
							<span class="wait">{x.overdueFollowUps}</span>
						</button>
					{:else}
						<Empty text="Nobody is behind." />
					{/each}
				{:else}
					<div class="li">
						<span></span>
						<span class="t">{myOverdue ? 'Follow-ups past their due date' : 'You are up to date'}</span>
						<span class="wait">{myOverdue || ''}</span>
					</div>
				{/if}
			</div>
		</div>
	</div>
</section>

<style>
	section {
		margin-top: 16px;
	}
	.cols {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}
	.cols.one {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
	.col + .col {
		border-left: 1px solid var(--sep);
	}
	h3 {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0;
		padding: 10px 1rem 4px;
		font-size: 13px;
		font-weight: 600;
	}
	.ct {
		color: var(--text2);
		font-weight: 400;
	}
	.wait {
		font-weight: 600;
		color: var(--red);
		font-variant-numeric: tabular-nums;
	}
	.av {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--sunk);
		color: var(--text2);
		font-size: 10.5px;
		font-weight: 600;
	}
	@media (max-width: 900px) {
		.cols,
		.cols.one {
			grid-template-columns: 1fr;
		}
		.col + .col {
			border-left: 0;
			border-top: 1px solid var(--sep);
		}
	}
</style>
