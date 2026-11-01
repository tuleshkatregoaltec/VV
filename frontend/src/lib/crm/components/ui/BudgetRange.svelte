<script lang="ts">
import { budgetBand } from '../../budgetBand'
import { fmt } from '../../format'

/**
 * States the price band portal listings are matched in (30% below to 20% above the budget).
 * The budget itself is changed in the lead's brief, which re-runs matching.
 */
let { budget, rent = false }: { budget: number; rent?: boolean } = $props()

const band = $derived(budgetBand(budget))
const per = $derived(rent ? ' a year' : '')
</script>

{#if band}
	<div class="small">
		Budget <b>AED {fmt(budget)}</b>{per} · portal listings priced AED {fmt(band.low)} to
		AED {fmt(band.high)}{per}
		<span class="muted">(30% below to 20% above)</span>
	</div>
{/if}
