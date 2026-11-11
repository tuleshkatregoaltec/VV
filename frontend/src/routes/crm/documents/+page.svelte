<script lang="ts">
/** CRM › Documents: every PDF generated from the agency's listings (same records as each listing's tab). */
import { replaceState } from '$app/navigation'
import { page } from '$app/state'
import type { DocType } from '$lib/crm/api/types'
import { DOC_TYPES } from '$lib/crm/components/documents/documentRules'
import GeneratedDocumentList from '$lib/crm/components/documents/GeneratedDocumentList.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'

type Filter = DocType | 'all'
const FILTERS: { id: Filter; label: string }[] = [
	{ id: 'all', label: 'All' },
	...DOC_TYPES.map((d) => ({ id: d.type, label: d.label }))
]

const fromUrl = page.url.searchParams.get('type')
let type = $state<Filter>(FILTERS.some((f) => f.id === fromUrl) ? (fromUrl as Filter) : 'all')
let search = $state(page.url.searchParams.get('q') ?? '')

// Filters live in the URL so a filtered list can be shared or reloaded.
$effect(() => {
	const url = new URL(page.url)
	if (type === 'all') url.searchParams.delete('type')
	else url.searchParams.set('type', type)
	if (search.trim()) url.searchParams.set('q', search.trim())
	else url.searchParams.delete('q')
	if (url.search !== page.url.search) {
		try {
			replaceState(url, {})
		} catch {
			// router not ready on the first render
		}
	}
})
</script>

<PageHeader title="Documents" facts="NOC, brochure, lease and A2A PDFs generated from your listings">
	{#snippet right()}
		<input class="search" type="search" placeholder="Search by listing" aria-label="Search by listing" bind:value={search} />
	{/snippet}
</PageHeader>

<div class="filters">
	<Seg items={FILTERS} value={type} label="Document type" onselect={(id) => (type = id)} />
</div>

<GeneratedDocumentList docType={type === 'all' ? undefined : type} {search} showListing />

<style>
	.filters {
		margin: 0 0 1rem;
	}
	.search {
		min-width: 14rem;
	}
</style>
