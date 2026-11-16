<script lang="ts">
/** Routing rules with a short explainer. Rules are applied where leads are issued (Leads imports). */
import ArrowDown from 'lucide-svelte/icons/arrow-down'
import ClipboardList from 'lucide-svelte/icons/clipboard-list'
import ListOrdered from 'lucide-svelte/icons/list-ordered'
import Upload from 'lucide-svelte/icons/upload'
import UserRound from 'lucide-svelte/icons/user-round'
import RoutingRules from './RoutingRules.svelte'
import SetupGuide from './SetupGuide.svelte'

let { editable, canManageTeams }: { editable: boolean; canManageTeams: boolean } = $props()
</script>

<div class="routing">
	{#if canManageTeams}<SetupGuide />{/if}
	<div class="workspace">
						<aside class="guide" aria-labelledby="how-routing-works">
						<h2 id="how-routing-works">How it works</h2>
						<ol class="steps">
							<li>
								<span class="step-number">1</span><Upload size={24} />
								<div><h3>New lead is imported</h3><p>In Leads, choose Routing rules when importing a lead file.</p></div>
							</li>
							<li class="connector" aria-hidden="true"><ArrowDown size={18} /></li>
							<li>
								<span class="step-number">2</span><ListOrdered size={24} />
								<div><h3>Rules are checked in order</h3><p>Top to bottom. The first matching enabled rule wins.</p></div>
							</li>
							<li class="connector" aria-hidden="true"><ArrowDown size={18} /></li>
							<li>
								<span class="step-number">3</span><UserRound size={24} />
								<div><h3>Lead is assigned</h3><p>To the agent selected in the matching rule.</p></div>
							</li>
						</ol>
						<div class="key-notes">
							<h3><ClipboardList size={18} /> Key notes</h3>
							<ul>
								<li>Rules run from top to bottom.</li>
								<li>The first matching rule wins.</li>
								<li>Applies to new imports only.</li>
								<li>Existing leads keep their current agent.</li>
								<li>A rule can move an unanswered lead to the next person, then to the team pool.</li>
								<li>A rule can route a lead only to people who speak its language.</li>
								<li>Shared leads go to the first agent who logs contact.</li>
							</ul>
						</div>
						</aside>
		<RoutingRules {editable} />
	</div>
</div>

<style>
	.routing {
		/* CRM theme tokens (crm.css), so routing matches the rest of the CRM in both themes. */
		--routing-blue: var(--accent-fill);
		--routing-tint: var(--sunk);
		--routing-border: var(--sep);
		display: grid;
		gap: 24px;
	}
	.workspace {
		display: grid;
		grid-template-columns: 255px minmax(0, 1fr);
		gap: 24px;
		align-items: start;
	}
	.guide {
		padding: 20px 16px;
		border: 1px solid var(--routing-border);
		border-radius: 12px;
		background: var(--routing-tint);
	}
	h2 {
		margin: 0 0 24px;
		font-size: 19px;
		font-weight: 700;
	}
	h3 {
		margin: 0;
		font-size: 14px;
		font-weight: 700;
		line-height: 1.5;
	}
	.steps {
		display: grid;
		gap: 16px;
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.steps li:not(.connector) {
		display: grid;
		grid-template-columns: 22px 24px minmax(0, 1fr);
		gap: 9px;
		align-items: start;
	}
	.step-number {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: color-mix(in srgb, var(--routing-blue) 20%, var(--card));
		font-size: 12px;
		font-weight: 700;
	}
	.steps p {
		margin: 6px 0 0;
		font-size: 13px;
		line-height: 1.6;
		color: var(--text2);
	}
	.connector {
		margin-left: 36px;
		color: var(--text3);
	}
	.key-notes {
		margin-top: 30px;
		padding: 14px;
		border: 1px solid var(--routing-border);
		border-radius: 10px;
		background: var(--routing-tint);
	}
	.key-notes h3 {
		display: flex;
		align-items: center;
		gap: 7px;
	}
	.key-notes ul {
		margin: 12px 0 0;
		padding-left: 18px;
		display: grid;
		gap: 8px;
		font-size: 13px;
		line-height: 1.5;
	}
	@media (max-width: 1100px) {
		.workspace {
			grid-template-columns: minmax(0, 1fr);
		}
		.guide {
			display: none;
		}
	}
</style>
