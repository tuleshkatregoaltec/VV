<script lang="ts">
import { createInfiniteQuery } from '@tanstack/svelte-query'
import { ImageIcon, MapPin, Search, Sparkles, X } from 'lucide-svelte'
import type { SupplyCatalogueProjectCardResponse } from '$lib/api/supply'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import { supplyQueries } from '$lib/queries/supply'

const PAGE_SIZE = 36

let search = $state('')
let selectedArea = $state('')
let selectedStatus = $state('Presale')
let sentinel = $state<HTMLDivElement | undefined>()

const catalogueFilters = $derived({
	search: search.trim() || undefined,
	area: selectedArea || undefined,
	status: selectedStatus || undefined
})

const catalogueQuery = createInfiniteQuery(() =>
	supplyQueries.catalogueInfinite(catalogueFilters, PAGE_SIZE)
)
const catalogueSummary = $derived(catalogueQuery.data?.pages[0])
const projects = $derived(catalogueQuery.data?.pages.flatMap((page) => page.projects) ?? [])
const heroProject = $derived(projects[0] ?? null)
const hasFilters = $derived(Boolean(search.trim() || selectedArea || selectedStatus))

$effect(() => {
	if (!sentinel) return

	const scrollRoot = sentinel.closest('.app-scroll-root')
	const observer = new IntersectionObserver(
		(entries) => {
			if (
				entries[0].isIntersecting &&
				catalogueQuery.hasNextPage &&
				!catalogueQuery.isFetchingNextPage
			) {
				catalogueQuery.fetchNextPage()
			}
		},
		{ root: scrollRoot, rootMargin: '900px 0px' }
	)

	observer.observe(sentinel)
	return () => observer.disconnect()
})

function formatMoney(value: number | null | undefined): string {
	if (value == null || value <= 0) return 'Price on request'
	if (value >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`
	if (value >= 1_000) return `AED ${(value / 1_000).toFixed(0)}K`
	return `AED ${value.toLocaleString()}`
}

function clearFilters() {
	search = ''
	selectedArea = ''
	selectedStatus = ''
}

function projectLocation(project: SupplyCatalogueProjectCardResponse): string {
	return project.area_name ?? project.region ?? 'Location TBD'
}

function hideBrokenImage(event: Event) {
	const image = event.currentTarget as HTMLImageElement | null
	image?.remove()
}
</script>

<svelte:head>
	<title>Upcoming Supply - Vitevue</title>
</svelte:head>

<AppFrame stableScrollGutter>
	<PageContainer variant="wide" class="gap-5">
		<section class="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
			<div class="grid min-h-[280px] lg:grid-cols-[1.05fr_0.95fr]">
				<div class="flex flex-col justify-between gap-8 p-5 sm:p-7">
					<div>
						<p class="font-mono text-[11px] uppercase tracking-[0.08em] text-fg-4">
							Upcoming / Supply catalogue
						</p>
						<div class="mt-3 flex flex-wrap items-end gap-3">
							<h1 class="text-3xl font-semibold tracking-normal text-fg-1 sm:text-4xl">
								New launch desk
							</h1>
							<span
								class="mb-1 inline-flex items-center gap-1.5 rounded-full bg-info-bg px-3 py-1 text-xs font-semibold text-info"
							>
								<Sparkles size={13} strokeWidth={2} />
								Launch feed
							</span>
						</div>
						<p class="mt-3 max-w-2xl text-sm leading-6 text-fg-3">
							Browse active and upcoming supply with developer visuals, brochures, floorplans,
							payment plans, launch timing, and unit ranges.
						</p>
					</div>

					<div class="grid gap-2 sm:grid-cols-3">
						<div class="rounded-md border border-border bg-panel px-3 py-3">
							<p class="font-mono text-[10px] uppercase tracking-[0.08em] text-fg-4">Projects</p>
							<p class="mt-1 text-2xl font-semibold tabular-nums text-fg-1">
									{catalogueSummary?.total?.toLocaleString() ?? '...'}
							</p>
						</div>
						<div class="rounded-md border border-border bg-panel px-3 py-3">
							<p class="font-mono text-[10px] uppercase tracking-[0.08em] text-fg-4">Markets</p>
							<p class="mt-1 text-2xl font-semibold tabular-nums text-fg-1">
									{catalogueSummary?.areas?.length ?? '...'}
							</p>
						</div>
						<div class="rounded-md border border-border bg-panel px-3 py-3">
							<p class="font-mono text-[10px] uppercase tracking-[0.08em] text-fg-4">
								Showing
							</p>
							<p class="mt-1 text-2xl font-semibold tabular-nums text-fg-1">
								{projects.length.toLocaleString()}
							</p>
						</div>
					</div>
				</div>

				<div class="relative min-h-[280px] bg-navy-900">
					<div class="absolute inset-0 bg-[linear-gradient(135deg,#0b1b2b,#183c4a_55%,#0f513f)]"></div>
					{#if heroProject?.cover_image_url}
							<img
								src={heroProject.cover_image_url}
								alt=""
								decoding="async"
								class="absolute inset-0 h-full w-full object-cover"
								onerror={hideBrokenImage}
							/>
						<div class="absolute inset-0 bg-linear-to-t from-black/72 via-black/18 to-transparent"></div>
					{/if}
					{#if heroProject}
						<div class="absolute inset-x-0 bottom-0 p-5 text-white sm:p-7">
							<div class="flex items-end gap-3">
								{#if heroProject.developer_logo_url}
									<img
											src={heroProject.developer_logo_url}
											alt=""
											decoding="async"
											class="h-12 w-12 rounded-md border border-white/30 bg-white object-contain p-1 shadow-md"
											onerror={hideBrokenImage}
										/>
								{/if}
								<div class="min-w-0">
									<p class="text-xs font-medium text-white/72">{heroProject.developer_name}</p>
									<p class="truncate text-xl font-semibold">{heroProject.project_name}</p>
									<p class="mt-1 text-xs text-white/70">{projectLocation(heroProject)}</p>
								</div>
							</div>
						</div>
					{/if}
				</div>
			</div>
		</section>

		<section class="space-y-3">
			<div class="grid gap-2 md:grid-cols-[minmax(0,1fr)_190px_190px_auto]">
				<label class="relative block">
					<Search
						size={15}
						strokeWidth={2}
						class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-4"
					/>
					<input
						bind:value={search}
						type="search"
						placeholder="Search projects, developers, areas"
						class="h-10 w-full rounded-md border border-border bg-card pl-9 pr-3 text-sm text-fg-1 outline-none transition-colors placeholder:text-fg-5 focus:border-border-focus"
					/>
				</label>

				<select
					bind:value={selectedArea}
					class="h-10 rounded-md border border-border bg-card px-3 text-sm text-fg-2 outline-none transition-colors focus:border-border-focus"
					aria-label="Filter by area"
				>
					<option value="">All areas</option>
						{#each catalogueSummary?.areas ?? [] as area (area)}
						<option value={area}>{area}</option>
					{/each}
				</select>

				<select
					bind:value={selectedStatus}
					class="h-10 rounded-md border border-border bg-card px-3 text-sm text-fg-2 outline-none transition-colors focus:border-border-focus"
					aria-label="Filter by status"
				>
					<option value="">All status</option>
						{#each catalogueSummary?.statuses ?? [] as status (status)}
						<option value={status}>{status}</option>
					{/each}
				</select>

				{#if hasFilters}
					<button
						type="button"
						onclick={clearFilters}
						class="ui-button h-10 px-3"
						data-variant="secondary"
					>
						<X size={14} strokeWidth={2} />
						Clear
					</button>
				{/if}
			</div>

			{#if catalogueQuery.isPending}
				<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
					{#each Array.from({ length: 12 }) as _, index (index)}
						<div class="h-[340px] animate-pulse rounded-lg border border-border bg-card"></div>
					{/each}
				</div>
			{:else if catalogueQuery.isError}
				<div class="rounded-lg border border-error-bg bg-error-bg p-6 text-sm text-error">
					Supply catalogue failed to load.
				</div>
			{:else if projects.length === 0}
				<div class="rounded-lg border border-border bg-card p-8 text-center">
					<p class="text-sm font-semibold text-fg-1">No matching projects</p>
					<p class="mt-1 text-sm text-fg-3">Try a broader area, status, or search term.</p>
				</div>
			{:else}
					<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
						{#each projects as project (project.project_id)}
						{@const unitTypes = project.unit_types ?? []}
							<a
								href={`/upcoming/${project.project_id}`}
								class="group isolate flex h-[340px] cursor-pointer flex-col overflow-hidden rounded-lg border border-border bg-card text-left shadow-sm transition-colors hover:border-border-strong [contain-intrinsic-size:340px] [contain:layout_paint_style] [content-visibility:auto]"
							>
								<div class="relative isolate h-40 overflow-hidden bg-panel">
									<div class="absolute inset-0 z-0 flex items-center justify-center text-fg-5">
										<ImageIcon size={28} strokeWidth={1.8} />
									</div>
									{#if project.cover_image_url}
										<img
											src={project.cover_image_url}
											alt=""
											loading="lazy"
											decoding="async"
											class="relative z-0 h-full w-full object-cover"
											onerror={hideBrokenImage}
										/>
									{/if}
									<div class="absolute left-3 top-3 z-20 rounded-full bg-navy/90 px-2 py-1 text-xs font-semibold text-white shadow-sm">
										{project.sale_status ?? 'Supply'}
									</div>
									{#if project.developer_logo_url}
									<img
										src={project.developer_logo_url}
											alt=""
											loading="lazy"
											decoding="async"
											class="absolute bottom-3 right-3 z-20 h-11 w-11 rounded-md border border-white/70 bg-white object-contain p-1 shadow-sm"
											onerror={hideBrokenImage}
										/>
								{/if}
							</div>

							<div class="flex min-h-0 flex-1 flex-col p-4">
								<div>
									<p class="truncate text-xs font-medium text-fg-4">{project.developer_name}</p>
									<h2 class="mt-1 line-clamp-2 text-base font-semibold leading-5 text-fg-1">
										{project.project_name}
									</h2>
									<div class="mt-2 flex items-center gap-1.5 text-xs text-fg-4">
										<MapPin size={13} strokeWidth={2} />
										<span class="truncate">{projectLocation(project)}</span>
									</div>
								</div>

								<div class="mt-auto">
									<div class="mb-3 flex flex-wrap gap-1.5">
										{#each unitTypes.slice(0, 2) as unitType (unitType)}
											<span class="rounded-full bg-info-bg px-2 py-1 text-[11px] font-medium text-info">
												{unitType}
											</span>
										{/each}
										{#if unitTypes.length > 2}
											<span class="rounded-full bg-panel px-2 py-1 text-[11px] font-medium text-fg-4">
												+{unitTypes.length - 2}
											</span>
										{/if}
									</div>
									<div class="flex items-end justify-between gap-3 text-xs">
										<div>
											<p class="text-fg-4">From</p>
											<p class="font-semibold text-fg-1">{formatMoney(project.min_price_aed)}</p>
										</div>
										<span class="text-right text-fg-4">{project.completion_date ?? 'Completion TBD'}</span>
									</div>
								</div>
							</div>
							</a>
							{/each}
						</div>
						<div bind:this={sentinel} class="h-px"></div>
						{#if catalogueQuery.isFetchingNextPage}
							<div class="py-5 text-center text-sm text-fg-4">Loading more projects...</div>
						{/if}
					{/if}
		</section>
	</PageContainer>
</AppFrame>
