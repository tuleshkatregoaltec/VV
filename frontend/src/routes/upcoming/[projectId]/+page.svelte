<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import {
	ArrowLeft,
	Building2,
	CalendarDays,
	Download,
	FileText,
	ImageIcon,
	Layers,
	MapPin,
	WalletCards
} from 'lucide-svelte'
import { page } from '$app/state'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import { supplyQueries } from '$lib/queries/supply'

const projectId = $derived(Number(page.params.projectId))
const projectQuery = createQuery(() =>
	supplyQueries.catalogueProject(Number.isFinite(projectId) ? projectId : null)
)
const project = $derived(projectQuery.data ?? null)
const brochures = $derived(project?.brochures ?? [])
const floorplans = $derived(project?.floorplans ?? [])
const gallery = $derived(project?.gallery ?? [])
const masterPlans = $derived(project?.master_plans ?? [])
const units = $derived(project?.units ?? [])
const paymentPlan = $derived(project?.payment_plan ?? [])
const facilities = $derived(project?.facilities ?? [])
const buildings = $derived(project?.buildings ?? [])
const nearbyPoints = $derived(project?.nearby_points ?? [])
const heroImage = $derived(project?.cover_image_url ?? gallery[0]?.url ?? '')
const projectSummary = $derived(
	compactText(project?.overview_excerpt ?? project?.overview) ||
		'Project overview is not available yet.'
)
const projectOverview = $derived(
	cleanDisplayText(project?.overview ?? project?.overview_excerpt) ||
		'Project overview is not available yet.'
)

function formatMoney(value: number | null | undefined): string {
	if (value == null || value <= 0) return 'Price on request'
	if (value >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`
	if (value >= 1_000) return `AED ${(value / 1_000).toFixed(0)}K`
	return `AED ${value.toLocaleString()}`
}

function formatArea(value: number | null | undefined): string {
	if (value == null) return 'Area TBD'
	return `${Math.round(value).toLocaleString()} sqft`
}

function formatRange(from: number | null | undefined, to: number | null | undefined): string {
	const validFrom = from && from > 0 ? from : null
	const validTo = to && to > 0 ? to : null
	if (validFrom == null && validTo == null) return 'Available on request'
	if (validFrom != null && validTo != null && validTo !== validFrom) {
		return `${formatMoney(validFrom)} - ${formatMoney(validTo)}`
	}
	return formatMoney(validFrom ?? validTo)
}

function cleanDisplayText(value: string | null | undefined): string {
	return (value ?? '')
		.replace(/\r\n/g, '\n')
		.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
		.replace(/^#{1,6}\s*/gm, '')
		.replace(/\*\*([^*]+)\*\*/g, '$1')
		.replace(/__([^_]+)__/g, '$1')
		.replace(/[`*_>]/g, '')
		.replace(/\n{3,}/g, '\n\n')
		.trim()
}

function compactText(value: string | null | undefined): string {
	return cleanDisplayText(value).replace(/\s+/g, ' ').trim()
}

function hideBrokenImage(event: Event) {
	const image = event.currentTarget as HTMLImageElement | null
	image?.remove()
}
</script>

<svelte:head>
	<title>{project?.project_name ?? 'Upcoming Supply'} - Vitevue</title>
</svelte:head>

<AppFrame stableScrollGutter>
	<PageContainer variant="wide" class="gap-5">
		<a href="/upcoming" class="inline-flex w-fit items-center gap-2 text-sm font-semibold text-fg-3 transition-colors hover:text-fg-1">
			<ArrowLeft size={15} strokeWidth={2} />
			Back to catalogue
		</a>

		{#if projectQuery.isPending}
			<div class="h-[620px] animate-pulse rounded-lg border border-border bg-card"></div>
		{:else if projectQuery.isError || !project}
			<div class="rounded-lg border border-error-bg bg-error-bg p-6 text-sm text-error">
				Project failed to load.
			</div>
		{:else}
			<section class="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
				<div class="relative min-h-[420px] bg-navy-900">
					<div class="absolute inset-0 bg-[linear-gradient(135deg,#0b1b2b,#183c4a_55%,#0f513f)]"></div>
					{#if heroImage}
						<img
							src={heroImage}
							alt=""
							class="absolute inset-0 h-full w-full object-cover"
							onerror={hideBrokenImage}
						/>
						<div class="absolute inset-0 bg-linear-to-t from-black/78 via-black/28 to-black/10"></div>
					{/if}

					<div class="relative flex min-h-[420px] flex-col justify-end p-5 text-white sm:p-8">
						<div class="max-w-4xl">
							<div class="mb-5 flex items-center gap-3">
								{#if project.developer_logo_url}
									<img
										src={project.developer_logo_url}
										alt=""
										class="h-14 w-14 rounded-md border border-white/30 bg-white object-contain p-1 shadow-md"
										onerror={hideBrokenImage}
									/>
								{/if}
								<div>
									<p class="text-sm font-medium text-white/74">{project.developer_name}</p>
									<p class="mt-1 flex items-center gap-1.5 text-sm text-white/70">
										<MapPin size={14} strokeWidth={2} />
										{project.area_name ?? project.region ?? 'Location TBD'}
									</p>
								</div>
							</div>

							<h1 class="max-w-3xl text-4xl font-semibold tracking-normal sm:text-5xl">
								{project.project_name}
							</h1>
							<p class="mt-4 max-w-3xl text-sm leading-6 text-white/78 sm:text-base">
								{projectSummary}
							</p>

							<div class="mt-6 flex flex-wrap gap-2">
								{#if brochures.length > 0}
									<a
										href={brochures[0].download_url ?? brochures[0].url}
										target="_blank"
										rel="noreferrer"
										download
										class="ui-button"
										data-variant="primary"
									>
										<Download size={15} strokeWidth={2} />
										Download catalogue
									</a>
								{/if}
							</div>
						</div>
					</div>
				</div>
			</section>

			<section class="grid gap-3 md:grid-cols-4">
				<div class="rounded-lg border border-border bg-card p-4 shadow-sm">
					<p class="text-xs text-fg-4">Status</p>
					<p class="mt-1 text-lg font-semibold text-fg-1">{project.status ?? 'TBD'}</p>
				</div>
				<div class="rounded-lg border border-border bg-card p-4 shadow-sm">
					<p class="text-xs text-fg-4">Sales status</p>
					<p class="mt-1 text-lg font-semibold text-fg-1">{project.sale_status ?? 'TBD'}</p>
				</div>
				<div class="rounded-lg border border-border bg-card p-4 shadow-sm">
					<p class="text-xs text-fg-4">Starting price</p>
					<p class="mt-1 text-lg font-semibold text-fg-1">{formatMoney(project.min_price_aed)}</p>
				</div>
				<div class="rounded-lg border border-border bg-card p-4 shadow-sm">
					<p class="text-xs text-fg-4">Completion</p>
					<p class="mt-1 text-lg font-semibold text-fg-1">{project.completion_date ?? 'TBD'}</p>
				</div>
			</section>

			<section class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
				<div class="space-y-4">
					<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
						<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
							<Building2 size={17} strokeWidth={2} />
							Project information
						</h2>
						<p class="whitespace-pre-line text-sm leading-7 text-fg-3">
							{projectOverview}
						</p>
					</div>

					{#if gallery.length > 0 || masterPlans.length > 0}
						<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
							<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
								<ImageIcon size={17} strokeWidth={2} />
								Gallery
							</h2>
							<div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
								{#each [...masterPlans, ...gallery].slice(0, 12) as asset (asset.id)}
									<a href={asset.url} target="_blank" rel="noreferrer" class="group block overflow-hidden rounded-md bg-panel">
										<div class="relative aspect-[4/3]">
											<div class="absolute inset-0 flex items-center justify-center text-fg-5">
												<ImageIcon size={24} strokeWidth={1.8} />
											</div>
											<img
												src={asset.url}
												alt=""
												loading="lazy"
												class="relative h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
												onerror={hideBrokenImage}
											/>
										</div>
									</a>
								{/each}
							</div>
						</div>
					{/if}

					{#if units.length > 0}
						<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
							<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
								<WalletCards size={17} strokeWidth={2} />
								Availability
							</h2>
							<div class="overflow-hidden rounded-md border border-border">
								{#each units as unit (unit.label)}
									<div class="grid gap-2 border-b border-border px-3 py-3 last:border-b-0 sm:grid-cols-[1fr_150px_170px]">
										<p class="text-sm font-semibold text-fg-1">{unit.label}</p>
										<p class="text-sm text-fg-3">{formatArea(unit.area_from_sqft)}</p>
										<p class="text-sm font-semibold text-fg-1">
											{formatRange(unit.price_from_aed, unit.price_to_aed)}
										</p>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>

				<aside class="space-y-4">
					<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
						<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
							<CalendarDays size={17} strokeWidth={2} />
							Timeline
						</h2>
						<div class="space-y-2 text-sm">
							<div class="flex items-center justify-between gap-3 rounded-md bg-panel px-3 py-2">
								<span class="text-fg-4">Sales status</span>
								<span class="font-semibold text-fg-1">{project.sale_status ?? 'TBD'}</span>
							</div>
							<div class="flex items-center justify-between gap-3 rounded-md bg-panel px-3 py-2">
								<span class="text-fg-4">Completion</span>
								<span class="font-semibold text-fg-1">{project.completion_date ?? 'TBD'}</span>
							</div>
						</div>
					</div>

					{#if paymentPlan.length > 0}
						<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
							<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
								<Layers size={17} strokeWidth={2} />
								Payment plan
							</h2>
							<div class="space-y-2">
								{#each paymentPlan as step, index (`${step.label}-${index}`)}
									<div class="flex items-center gap-3 rounded-md bg-panel px-3 py-2">
										<div class="flex h-8 w-8 items-center justify-center rounded-full bg-card text-xs font-semibold text-info">
											{step.percent ? `${step.percent}%` : index + 1}
										</div>
										<p class="text-sm text-fg-2">{step.label}</p>
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
						<h2 class="mb-3 flex items-center gap-2 text-base font-semibold text-fg-1">
							<FileText size={17} strokeWidth={2} />
							Documents
						</h2>
						<div class="space-y-2">
							{#each brochures as brochure (brochure.id)}
								<a
									href={brochure.download_url ?? brochure.url}
									target="_blank"
									rel="noreferrer"
									download
									class="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:border-border-strong hover:bg-panel"
								>
									<span class="truncate">{brochure.name ?? 'Catalogue'}</span>
									<Download size={14} strokeWidth={2} class="flex-shrink-0 text-fg-4" />
								</a>
							{/each}
							{#each floorplans as floorplan (floorplan.id)}
								<a
									href={floorplan.download_url ?? floorplan.url}
									target="_blank"
									rel="noreferrer"
									download
									class="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:border-border-strong hover:bg-panel"
								>
									<span class="truncate">{floorplan.name ?? 'Floorplan'}</span>
									<Download size={14} strokeWidth={2} class="flex-shrink-0 text-fg-4" />
								</a>
							{/each}
							{#if brochures.length === 0 && floorplans.length === 0}
								<p class="rounded-md bg-panel px-3 py-2 text-sm text-fg-4">
									No documents attached to this project yet.
								</p>
							{/if}
						</div>
					</div>

					{#if facilities.length > 0}
						<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
							<h2 class="mb-3 text-base font-semibold text-fg-1">Facilities</h2>
							<div class="flex flex-wrap gap-1.5">
								{#each facilities.slice(0, 18) as facility (facility)}
									<span class="rounded-full bg-info-bg px-2 py-1 text-xs font-medium text-info">
										{facility}
									</span>
								{/each}
							</div>
						</div>
					{/if}

					{#if buildings.length > 0 || nearbyPoints.length > 0}
						<div class="rounded-lg border border-border bg-card p-5 shadow-sm">
							<h2 class="mb-3 text-base font-semibold text-fg-1">Site notes</h2>
							<div class="space-y-3 text-sm text-fg-3">
								{#each buildings.slice(0, 3) as building (building.name)}
									<p>
										<span class="font-semibold text-fg-1">{building.name}</span>
										{#if building.description}
											<span> - {building.description}</span>
										{/if}
									</p>
								{/each}
								{#if nearbyPoints.length > 0}
									<p class="font-semibold text-fg-1">Nearby</p>
									{#each nearbyPoints.slice(0, 5) as point (point.name)}
										<p>{point.name}{point.distance_km ? ` · ${point.distance_km}km` : ''}</p>
									{/each}
								{/if}
							</div>
						</div>
					{/if}
				</aside>
			</section>
		{/if}
	</PageContainer>
</AppFrame>
