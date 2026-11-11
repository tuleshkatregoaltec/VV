<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { fmt, price } from '../../format'
import { crmQueries } from '../../queries'
import { openListing } from '../../stores/panel.svelte'
import GenerateActions from '../documents/GenerateActions.svelte'
import GeneratedDocumentList from '../documents/GeneratedDocumentList.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'

/** What the one-page A4 brochure shows, and the brochure PDFs made for this listing. */
let { id }: { id: string } = $props()
const listing = createQuery(() => crmQueries.listing(id))
</script>

{#if listing.data}
	{@const x = listing.data}
	{@const key = x.scope === 'company' && x.managed ? x.listing_key : undefined}
	{@const rows = [
		['Price', price(x.deal_type, x.price_aed)],
		['Size', `${x.bedrooms ? `${x.bedrooms} bedrooms` : 'Studio'} · ${fmt(x.size_sqft)} sqft`],
		['Area', x.area],
		...(x.comparables_note ? [['Recent sales', x.comparables_note]] : []),
		// Only a recorded permit is printed; nothing stands in for a missing one.
		...(x.permit ? [['Permit', `Trakheesi ${x.permit.number}`]] : []),
		['Agent', x.agent]
	]}
	<Panel kicker="Brochure PDF" title={x.unit} sub="One page, A4">
		<div class="paper">
			<h4><span>{x.unit}</span><span style="font-weight:400;color:#666">{x.area}</span></h4>
			{#each rows as [k, v] (k)}
				<div class="pf"><span>{k}</span><span>{v}</span></div>
			{/each}
		</div>
		{#if key}
			<GenerateActions listingKey={key} only="brochure" />
			<GeneratedDocumentList listingKey={key} docType="brochure" />
		{:else}
			<div class="small muted">Brochure PDFs can be made for your agency's connected company listings.</div>
		{/if}
		{#snippet footer()}
			<button type="button" class="btn ghost" onclick={() => openListing(id, key ? 'documents' : undefined)}>
				Back to the listing
			</button>
		{/snippet}
	</Panel>
{:else}
	<PanelLoading query={listing} kicker="Brochure PDF" />
{/if}
