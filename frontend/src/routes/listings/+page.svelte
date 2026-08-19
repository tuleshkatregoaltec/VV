<script lang="ts">
import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query'
import {
	BadgeCheck,
	Bath,
	BedDouble,
	Building2,
	DraftingCompass,
	ExternalLink,
	Home,
	ImageIcon,
	LayoutGrid,
	LayoutList,
	Mail,
	MapPin,
	Phone,
	Search,
	ShieldCheck,
	Square,
	UserRound,
	X
} from 'lucide-svelte'
import type {
	ListingCardResponse,
	ListingDetailResponse,
	ListingImageResponse,
	ListingMode,
	ListingPartyResponse
} from '$lib/api/listings'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import { listingQueries } from '$lib/queries/listings'

const PAGE_SIZE = 24
const FILTER_DEBOUNCE_MS = 250

type ListingViewMode = 'grid' | 'list'

let mode = $state<ListingMode>('rent')
let viewMode = $state<ListingViewMode>('grid')
let selectedListingId = $state<string | null>(null)
let search = $state('')
let selectedArea = $state('')
let selectedPropertyType = $state('')
let selectedBedrooms = $state('')
let priceMin = $state('')
let priceMax = $state('')
let debouncedSearch = $state('')
let debouncedPriceMin = $state('')
let debouncedPriceMax = $state('')
let activeImageUrl = $state<string | null>(null)
let sentinel = $state<HTMLDivElement | undefined>()

const listingFilters = $derived({
	mode,
	search: debouncedSearch || undefined,
	area: selectedArea || undefined,
	property_type: selectedPropertyType || undefined,
	bedrooms: selectedBedrooms || undefined,
	price_min: parsePriceFilter(debouncedPriceMin),
	price_max: parsePriceFilter(debouncedPriceMax)
})

const listingsQuery = createInfiniteQuery(() =>
	listingQueries.listInfinite(listingFilters, PAGE_SIZE)
)
const analyticsQuery = createQuery(() => listingQueries.analytics(listingFilters))
const detailQuery = createQuery(() => listingQueries.detail(selectedListingId))

const listingSummary = $derived(listingsQuery.data?.pages[0])
const listings = $derived(listingsQuery.data?.pages.flatMap((page) => page.listings) ?? [])
const filters = $derived(listingSummary?.filters)
const analytics = $derived(analyticsQuery.data)
const selectedListing = $derived<ListingDetailResponse | null>(detailQuery.data ?? null)
const activeCard = $derived.by(() => {
	if (selectedListingId) {
		const match = listings.find((listing) => listing.listing_id === selectedListingId)
		if (match) return match
	}
	return listings[0] ?? null
})
const heroImage = $derived(
	activeImageUrl ??
		imageUrl(selectedListing?.images?.[0]) ??
		selectedListing?.primary_image_url ??
		activeCard?.primary_image_url ??
		null
)
const hasFilters = $derived(
	Boolean(
		search.trim() ||
			selectedArea ||
			selectedPropertyType ||
			selectedBedrooms ||
			priceMin.trim() ||
			priceMax.trim()
	)
)
const saleCount = $derived(mode === 'sale' ? listingSummary?.total : undefined)
const rentCount = $derived(mode === 'rent' ? listingSummary?.total : undefined)

$effect(() => {
	if (!sentinel) return

	const scrollRoot = sentinel.closest('.app-scroll-root')
	const observer = new IntersectionObserver(
		(entries) => {
			if (
				entries[0].isIntersecting &&
				listingsQuery.hasNextPage &&
				!listingsQuery.isFetchingNextPage
			) {
				listingsQuery.fetchNextPage()
			}
		},
		{ root: scrollRoot, rootMargin: '900px 0px' }
	)

	observer.observe(sentinel)
	return () => observer.disconnect()
})

$effect(() => {
	if (listings.length === 0) {
		selectedListingId = null
		activeImageUrl = null
		return
	}
	if (!selectedListingId || !listings.some((listing) => listing.listing_id === selectedListingId)) {
		selectedListingId = listings[0].listing_id
		activeImageUrl = null
	}
})

$effect(() => {
	if (!selectedListing) return
	activeImageUrl =
		imageUrl(selectedListing.images?.[0]) ?? selectedListing.primary_image_url ?? null
})

$effect(() => {
	const nextSearch = search.trim()
	const nextPriceMin = priceMin.trim()
	const nextPriceMax = priceMax.trim()
	const timeout = setTimeout(() => {
		debouncedSearch = nextSearch
		debouncedPriceMin = nextPriceMin
		debouncedPriceMax = nextPriceMax
	}, FILTER_DEBOUNCE_MS)

	return () => clearTimeout(timeout)
})

function parsePriceFilter(value: string): number | undefined {
	const normalized = value.trim().replaceAll(',', '')
	if (!normalized) return undefined
	const parsed = Number(normalized)
	return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
}

function imageUrl(image: ListingImageResponse | null | undefined): string | null {
	if (!image) return null
	return image.medium_url ?? image.small_url ?? image.original_url ?? image.url ?? null
}

function setMode(nextMode: ListingMode) {
	if (mode === nextMode) return
	mode = nextMode
	selectedListingId = null
	activeImageUrl = null
	clearFilters()
}

function selectListing(listing: ListingCardResponse) {
	selectedListingId = listing.listing_id
	activeImageUrl = listing.primary_image_url ?? null
}

function clearFilters() {
	search = ''
	selectedArea = ''
	selectedPropertyType = ''
	selectedBedrooms = ''
	priceMin = ''
	priceMax = ''
	debouncedSearch = ''
	debouncedPriceMin = ''
	debouncedPriceMax = ''
}

function formatCompactCount(value: number | null | undefined, fallback = '2.5K'): string {
	if (value == null) return fallback
	if (value >= 10_000) return `${Math.round(value / 1000)}K`
	if (value >= 1_000) return `${(value / 1000).toFixed(1)}K`
	return value.toLocaleString()
}

function formatMoney(value: number | null | undefined, period?: string | null): string {
	if (value == null || value <= 0) return 'Price on request'
	let label: string
	if (value >= 1_000_000_000) label = `AED ${(value / 1_000_000_000).toFixed(2)}B`
	else if (value >= 1_000_000)
		label = `AED ${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`
	else if (value >= 1_000) label = `AED ${(value / 1_000).toFixed(0)}K`
	else label = `AED ${value.toLocaleString()}`

	if (!period || period === 'sell') return label
	return `${label}/${period.replace('ly', '')}`
}

function formatStatMoney(value: number | null | undefined): string {
	return value == null ? '...' : formatMoney(value)
}

function formatArea(value: number | null | undefined, unit: string | null | undefined): string {
	if (value == null || value <= 0) return 'Area unavailable'
	return `${Math.round(value).toLocaleString()} ${unit ?? 'sqft'}`
}

function formatDate(value: string | null | undefined): string {
	if (!value) return 'Date unavailable'
	const date = new Date(value)
	if (Number.isNaN(date.getTime())) return 'Date unavailable'
	return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function pricePerSqft(listing: ListingCardResponse): number | null {
	if (!listing.price_value || !listing.size_value || listing.size_value <= 0) return null
	return listing.price_value / listing.size_value
}

function partyInitials(party: ListingPartyResponse | null | undefined): string {
	const name = party?.name ?? 'Agent'
	return name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0]?.toUpperCase())
		.join('')
}

function hideBrokenImage(event: Event) {
	const image = event.currentTarget as HTMLImageElement | null
	image?.remove()
}
</script>

<svelte:head>
	<title>Listings - Vitevue</title>
</svelte:head>

<AppFrame stableScrollGutter>
	<PageContainer variant="wide" class="gap-5">
		<section class="ui-surface relative z-30 overflow-visible">
			<div class="ui-page-header grid gap-4 px-5 py-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
				<div>
					<p class="text-xs font-semibold uppercase tracking-[0.18em] text-on-navy-muted">
						Marketplace inventory
					</p>
					<h1 class="mt-1 font-display text-2xl leading-tight tracking-[var(--tracking-display)] text-bone">
						Listings
					</h1>
				</div>

				<div class="mt-4 flex flex-wrap items-center gap-2 xl:mt-0 xl:justify-end">
					<nav class="ui-segmented" aria-label="Listing type">
						<button
							type="button"
							data-active={mode === 'rent'}
							class="ui-segmented-item px-3 py-1.5 text-sm"
							onclick={() => setMode('rent')}
						>
							Rentals
						</button>
						<button
							type="button"
							data-active={mode === 'sale'}
							class="ui-segmented-item px-3 py-1.5 text-sm"
							onclick={() => setMode('sale')}
						>
							Sales
						</button>
					</nav>

					<div class="rounded-md border border-white/15 bg-white/10 px-3 py-2 text-sm font-semibold text-bone">
						{mode === 'rent' ? formatCompactCount(rentCount, '...') : formatCompactCount(saleCount, '...')}
						<span class="font-normal text-on-navy-muted">
							{mode === 'rent' ? ' rental listings' : ' sales listings'}
						</span>
					</div>
				</div>
			</div>
		</section>

		<section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px] xl:gap-0">
			<div class="min-w-0 xl:pr-5">
				<div class="mb-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
					<div class="ui-surface p-3">
						<p class="text-xs font-medium text-fg-4">Available inventory</p>
						<p class="mt-1 text-xl font-semibold tabular-nums text-fg-1">{analytics?.total?.toLocaleString() ?? '...'}</p>
					</div>
					<div class="ui-surface p-3">
						<p class="text-xs font-medium text-fg-4">Median asking price</p>
						<p class="mt-1 text-xl font-semibold tabular-nums text-fg-1">{formatStatMoney(analytics?.median_price_aed)}</p>
					</div>
					<div class="ui-surface p-3">
						<p class="text-xs font-medium text-fg-4">Median AED / sqft</p>
						<p class="mt-1 text-xl font-semibold tabular-nums text-fg-1">{analytics?.median_price_per_sqft_aed ? `AED ${Math.round(analytics.median_price_per_sqft_aed).toLocaleString()}` : '—'}</p>
					</div>
					<div class="ui-surface p-3">
						<p class="text-xs font-medium text-fg-4">Verified share</p>
						<p class="mt-1 text-xl font-semibold tabular-nums text-fg-1">{analytics?.total ? `${Math.round((analytics.verified_count / analytics.total) * 100)}%` : '—'}</p>
						<p class="mt-0.5 text-xs text-fg-4">{analytics?.area_count?.toLocaleString() ?? '...'} areas</p>
					</div>
				</div>

				<div class="ui-surface mb-3 overflow-visible p-3">
					<div class="grid gap-2 lg:grid-cols-[minmax(0,1.2fr)_160px_160px_120px_120px_120px_auto]">
						<label class="relative block">
							<Search
								size={15}
								strokeWidth={2}
								class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-4"
							/>
							<input
								bind:value={search}
								type="search"
								placeholder="Search listings, buildings, agents"
								class="ui-field h-10 w-full pl-9 pr-3 text-sm"
							/>
						</label>

						<select bind:value={selectedArea} class="ui-field h-10 px-3 text-sm" aria-label="Area">
							<option value="">All areas</option>
							{#each filters?.areas ?? [] as area (area)}
								<option value={area}>{area}</option>
							{/each}
						</select>

						<select
							bind:value={selectedPropertyType}
							class="ui-field h-10 px-3 text-sm"
							aria-label="Property type"
						>
							<option value="">All types</option>
							{#each filters?.property_types ?? [] as propertyType (propertyType)}
								<option value={propertyType}>{propertyType}</option>
							{/each}
						</select>

						<select
							bind:value={selectedBedrooms}
							class="ui-field h-10 px-3 text-sm"
							aria-label="Bedrooms"
						>
							<option value="">Beds</option>
							{#each filters?.bedrooms ?? [] as bedroom (bedroom)}
								<option value={bedroom}>{bedroom === 'studio' ? 'Studio' : `${bedroom} bed`}</option>
							{/each}
						</select>

						<input
							bind:value={priceMin}
							type="text"
							inputmode="numeric"
							placeholder="Min AED"
							class="ui-field h-10 px-3 text-sm"
							aria-label="Minimum price"
						/>
						<input
							bind:value={priceMax}
							type="text"
							inputmode="numeric"
							placeholder="Max AED"
							class="ui-field h-10 px-3 text-sm"
							aria-label="Maximum price"
						/>

						{#if hasFilters}
							<button type="button" onclick={clearFilters} class="ui-button h-10 px-3" data-variant="secondary">
								<X size={14} strokeWidth={2} />
								Clear
							</button>
						{/if}
					</div>
				</div>

				<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
					<p class="text-sm text-fg-3">
						<span class="font-semibold text-fg-1">{listingSummary?.total?.toLocaleString() ?? '...'}</span>
						{mode === 'rent' ? 'rental' : 'sales'} listings
					</p>
					<div class="flex flex-wrap items-center justify-end gap-2">
						<nav class="ui-segmented" aria-label="Listing layout">
							<button
								type="button"
								data-active={viewMode === 'grid'}
								class="ui-segmented-item inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs"
								onclick={() => (viewMode = 'grid')}
							>
								<LayoutGrid size={14} strokeWidth={2} />
								Grid
							</button>
							<button
								type="button"
								data-active={viewMode === 'list'}
								class="ui-segmented-item inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs"
								onclick={() => (viewMode = 'list')}
							>
								<LayoutList size={14} strokeWidth={2} />
								List
							</button>
						</nav>
					</div>
				</div>

				{#if listingsQuery.isPending}
					<div class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
						{#each Array.from({ length: 6 }) as _, index (index)}
							<div class="h-[335px] animate-pulse rounded-lg border border-border bg-card"></div>
						{/each}
					</div>
				{:else if listingsQuery.isError}
					<div class="rounded-lg border border-error-bg bg-error-bg p-6 text-sm text-error">
						Listings failed to load.
					</div>
				{:else if listings.length === 0}
					<div class="rounded-lg border border-border bg-card p-8 text-center">
						<p class="text-sm font-semibold text-fg-1">No matching listings</p>
						<p class="mt-1 text-sm text-fg-3">Try a broader area, price, or search term.</p>
					</div>
				{:else if viewMode === 'grid'}
					<div class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
						{#each listings as listing (listing.listing_id)}
							<button
								type="button"
								onclick={() => selectListing(listing)}
								class="group flex h-[340px] cursor-pointer flex-col overflow-hidden rounded-lg border bg-card text-left shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-md {selectedListingId ===
								listing.listing_id
									? 'border-info'
									: 'border-border hover:border-border-strong'}"
								aria-pressed={selectedListingId === listing.listing_id}
							>
								<div class="relative isolate h-40 shrink-0 overflow-hidden bg-panel">
									<div class="absolute inset-0 grid place-items-center text-fg-5">
										<ImageIcon size={28} strokeWidth={1.8} />
									</div>
									{#if listing.primary_image_url}
										<img
											src={listing.primary_image_url}
											alt=""
											loading="lazy"
											decoding="async"
											referrerpolicy="no-referrer"
											class="relative h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
											onerror={hideBrokenImage}
										/>
									{/if}
									<div class="pointer-events-none absolute left-3 top-3 z-10 max-w-[calc(100%-1.5rem)] truncate rounded-full bg-black/75 px-2 py-1 text-xs font-semibold text-white shadow-sm">
										{formatMoney(listing.price_value, listing.price_period)}
									</div>
									{#if listing.broker_logo_url}
										<img
											src={listing.broker_logo_url}
											alt=""
											loading="lazy"
											decoding="async"
											referrerpolicy="no-referrer"
											class="absolute bottom-3 right-3 z-10 h-11 w-11 rounded-md border border-white/70 bg-white object-contain p-1 shadow-sm"
											onerror={hideBrokenImage}
										/>
									{/if}
								</div>

								<div class="flex min-h-0 flex-1 flex-col p-4">
									<div>
										<p class="truncate text-xs font-medium text-fg-4">
											{listing.property_type ?? 'Property'}
										</p>
										<h2 class="mt-1 line-clamp-2 text-base font-semibold leading-5 text-fg-1">
											{listing.title}
										</h2>
										<div class="mt-2 flex items-center gap-1.5 text-xs text-fg-4">
											<MapPin size={13} strokeWidth={2} />
											<span class="truncate">{listing.tower_name ?? listing.subcommunity_name ?? listing.area_name ?? 'Location unavailable'}</span>
										</div>
									</div>

									<div class="mt-auto space-y-3">
										<div class="grid grid-cols-3 gap-2 text-xs text-fg-3">
											<div class="flex items-center gap-1.5">
												<BedDouble size={13} strokeWidth={2} />
												<span>{listing.bedrooms ?? '-'}</span>
											</div>
											<div class="flex items-center gap-1.5">
												<Bath size={13} strokeWidth={2} />
												<span>{listing.bathrooms ?? '-'}</span>
											</div>
											<div class="flex items-center gap-1.5">
												<Square size={13} strokeWidth={2} />
												<span class="truncate">{formatArea(listing.size_value, listing.size_unit)}</span>
											</div>
										</div>
										<div class="flex items-center justify-between gap-3 border-t border-border pt-3">
											<div class="min-w-0">
												<p class="truncate text-xs font-medium text-fg-1">
													{listing.agent_name ?? listing.broker_name ?? 'Seller unavailable'}
												</p>
												<p class="truncate text-[11px] text-fg-4">{listing.broker_name ?? 'Broker unavailable'}</p>
											</div>
											{#if listing.is_verified}
												<div class="flex items-center gap-1 text-info">
													<BadgeCheck size={15} strokeWidth={2} />
													<span class="text-xs font-semibold">Verified</span>
												</div>
											{/if}
										</div>
									</div>
								</div>
							</button>
						{/each}
					</div>
					<div bind:this={sentinel} class="h-px"></div>
					{#if listingsQuery.isFetchingNextPage}
						<div class="py-5 text-center text-sm text-fg-4">Loading more listings...</div>
					{/if}
				{:else}
					<div class="grid gap-2">
						{#each listings as listing (listing.listing_id)}
							<button
								type="button"
								onclick={() => selectListing(listing)}
								class="group grid w-full cursor-pointer gap-4 rounded-lg border p-4 text-left shadow-sm transition duration-200 hover:shadow-md lg:items-center lg:grid-cols-[minmax(0,1.1fr)_minmax(220px,0.7fr)_minmax(180px,0.55fr)_118px] {selectedListingId ===
								listing.listing_id
									? 'border-info bg-info-bg'
									: 'border-border bg-card hover:border-border-strong hover:bg-elevated'}"
								aria-pressed={selectedListingId === listing.listing_id}
							>
								<div class="min-w-0">
									<div class="flex min-w-0 items-center gap-2">
										<p class="truncate text-xs font-medium text-fg-4">
											{listing.property_type ?? 'Property'}
										</p>
										{#if listing.is_verified}
											<span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-success-bg px-2 py-0.5 text-[11px] font-semibold text-success">
												<BadgeCheck size={12} strokeWidth={2} />
												Verified
											</span>
										{/if}
									</div>
									<h2 class="mt-1 line-clamp-2 text-base font-semibold leading-5 text-fg-1">
										{listing.title}
									</h2>
									<div class="mt-2 flex items-center gap-1.5 text-xs text-fg-4">
										<MapPin size={13} strokeWidth={2} />
										<span class="truncate">{listing.tower_name ?? listing.subcommunity_name ?? listing.area_name ?? 'Location unavailable'}</span>
									</div>
								</div>

								<div class="grid gap-2 text-sm">
									<p class="font-semibold text-fg-1">
										{formatMoney(listing.price_value, listing.price_period)}
									</p>
									<div class="grid grid-cols-3 gap-2 text-xs text-fg-3">
										<div class="flex min-w-0 items-center gap-1.5">
											<BedDouble size={13} strokeWidth={2} />
											<span>{listing.bedrooms ?? '-'}</span>
										</div>
										<div class="flex min-w-0 items-center gap-1.5">
											<Bath size={13} strokeWidth={2} />
											<span>{listing.bathrooms ?? '-'}</span>
										</div>
										<div class="flex min-w-0 items-center gap-1.5">
											<Square size={13} strokeWidth={2} />
											<span class="truncate">{formatArea(listing.size_value, listing.size_unit)}</span>
										</div>
									</div>
								</div>

								<div class="min-w-0">
									<p class="truncate text-xs font-medium text-fg-1">
										{listing.agent_name ?? listing.broker_name ?? 'Seller unavailable'}
									</p>
									<p class="mt-1 truncate text-[11px] text-fg-4">{listing.broker_name ?? 'Broker unavailable'}</p>
								</div>

								{#if pricePerSqft(listing)}
									<div class="justify-self-start rounded-md border border-border bg-panel px-2.5 py-2 text-left lg:justify-self-end lg:text-right">
										<p class="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-4">AED / sqft</p>
										<p class="mt-0.5 text-sm font-semibold tabular-nums text-fg-1">AED {Math.round(pricePerSqft(listing) ?? 0).toLocaleString()}</p>
									</div>
								{/if}
							</button>
						{/each}
					</div>
					<div bind:this={sentinel} class="h-px"></div>
					{#if listingsQuery.isFetchingNextPage}
						<div class="py-5 text-center text-sm text-fg-4">Loading more listings...</div>
					{/if}
				{/if}
			</div>

			<aside class="min-w-0 xl:sticky xl:top-5 xl:self-start xl:border-l xl:border-border xl:pl-5">
				<div class="overflow-hidden rounded-lg border border-border bg-card shadow-sm xl:max-h-[calc(100dvh-6.5rem)] xl:overflow-y-auto xl:overscroll-contain">
					{#if !activeCard}
						<div class="p-6 text-sm text-fg-3">Select a listing to view details.</div>
					{:else}
						<div class="relative h-64 bg-panel">
							<div class="absolute inset-0 grid place-items-center text-fg-5">
								<ImageIcon size={34} strokeWidth={1.8} />
							</div>
							{#if heroImage}
								<img
									src={heroImage}
									alt=""
									decoding="async"
									referrerpolicy="no-referrer"
									class="relative h-full w-full object-cover"
									onerror={hideBrokenImage}
								/>
								<div class="absolute inset-0 bg-linear-to-t from-black/75 via-black/10 to-transparent"></div>
							{/if}

							<div class="absolute inset-x-0 bottom-0 p-4 text-white">
								<p class="text-xs text-white/75">{activeCard.property_type ?? 'Property'}</p>
								<h2 class="mt-1 line-clamp-2 text-xl font-semibold leading-6">{activeCard.title}</h2>
								<div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-white/80">
									<span>{activeCard.area_name ?? 'Dubai'}</span>
									<span aria-hidden="true">/</span>
									<span>{formatMoney(activeCard.price_value, activeCard.price_period)}</span>
								</div>
							</div>
						</div>

						{#if selectedListing?.images?.length}
							<div class="grid grid-cols-5 gap-2 border-b border-border p-3">
								{#each selectedListing.images.slice(0, 10) as image, index (`${imageUrl(image)}-${index}`)}
									{@const thumbUrl = imageUrl(image)}
									{#if thumbUrl}
										<button
											type="button"
											onclick={() => (activeImageUrl = thumbUrl)}
											class="h-16 min-w-0 cursor-pointer overflow-hidden rounded-md border transition {activeImageUrl ===
											thumbUrl
												? 'border-info'
												: 'border-border hover:border-border-strong'}"
											aria-label={`Show listing image ${index + 1}`}
										>
											<img
												src={thumbUrl}
												alt=""
												loading="lazy"
												decoding="async"
												referrerpolicy="no-referrer"
												class="h-full w-full object-cover"
												onerror={hideBrokenImage}
											/>
										</button>
									{/if}
								{/each}
							</div>
						{/if}

						<div class="space-y-5 p-4">
							<div class="grid grid-cols-3 gap-2">
								<div class="rounded-md bg-panel p-3">
									<p class="text-[11px] text-fg-4">Beds</p>
									<p class="mt-1 truncate text-sm font-semibold text-fg-1">
										{activeCard.bedrooms ?? '-'}
									</p>
								</div>
								<div class="rounded-md bg-panel p-3">
									<p class="text-[11px] text-fg-4">Baths</p>
									<p class="mt-1 truncate text-sm font-semibold text-fg-1">
										{activeCard.bathrooms ?? '-'}
									</p>
								</div>
								<div class="rounded-md bg-panel p-3">
									<p class="text-[11px] text-fg-4">Area</p>
									<p class="mt-1 truncate text-sm font-semibold text-fg-1">
										{formatArea(activeCard.size_value, activeCard.size_unit)}
									</p>
								</div>
							</div>

							{#if detailQuery.isFetching && !selectedListing}
								<div class="space-y-2">
									<div class="h-4 w-full animate-pulse rounded bg-panel"></div>
									<div class="h-4 w-5/6 animate-pulse rounded bg-panel"></div>
									<div class="h-4 w-3/5 animate-pulse rounded bg-panel"></div>
								</div>
							{:else if selectedListing}
								<div class="flex flex-wrap gap-2">
									{#if selectedListing.share_url}
										<a
											href={selectedListing.share_url}
											target="_blank"
											rel="noreferrer"
											class="ui-button h-10 flex-1 px-3"
											data-variant="primary"
										>
											<ExternalLink size={15} strokeWidth={2} />
											Open listing
										</a>
									{/if}
									{#if selectedListing.agent?.phone}
										<a href={`tel:${selectedListing.agent.phone}`} class="ui-button h-10 px-3" data-variant="secondary">
											<Phone size={15} strokeWidth={2} />
										</a>
									{/if}
									{#if selectedListing.agent?.email}
										<a href={`mailto:${selectedListing.agent.email}`} class="ui-button h-10 px-3" data-variant="secondary">
											<Mail size={15} strokeWidth={2} />
										</a>
									{/if}
								</div>

								<div>
									<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
										<Home size={15} strokeWidth={2} />
										Property
									</h3>
									<p class="text-sm leading-6 text-fg-3">
										{selectedListing.description ?? 'Description unavailable.'}
									</p>
								</div>

								<div>
									<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
										<MapPin size={15} strokeWidth={2} />
										Location
									</h3>
									<div class="space-y-2 text-sm">
										<div class="rounded-md bg-panel px-3 py-2">
											<p class="font-semibold text-fg-1">
												{selectedListing.location_name ?? 'Location unavailable'}
											</p>
											<p class="mt-1 text-xs text-fg-4">
												{selectedListing.latitude?.toFixed(5) ?? '-'}, {selectedListing.longitude?.toFixed(5) ?? '-'}
											</p>
										</div>
									</div>
								</div>

								<div>
									<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
										<UserRound size={15} strokeWidth={2} />
										Seller
									</h3>
									<div class="rounded-md border border-border p-3">
										<div class="flex items-center gap-3">
											{#if selectedListing.agent?.image_url}
												<img
													src={selectedListing.agent.image_url}
													alt=""
													loading="lazy"
													decoding="async"
													referrerpolicy="no-referrer"
													class="h-12 w-12 rounded-md object-cover"
													onerror={hideBrokenImage}
												/>
											{:else}
												<div class="grid h-12 w-12 shrink-0 place-items-center rounded-md bg-panel text-sm font-semibold text-fg-2">
													{partyInitials(selectedListing.agent)}
												</div>
											{/if}
											<div class="min-w-0">
												<p class="truncate text-sm font-semibold text-fg-1">
													{selectedListing.agent?.name ?? 'Agent unavailable'}
												</p>
												<p class="truncate text-xs text-fg-4">
													{selectedListing.broker?.name ?? selectedListing.client?.name ?? 'Broker unavailable'}
												</p>
											</div>
										</div>
										{#if selectedListing.broker?.logo_url || selectedListing.broker?.phone || selectedListing.broker?.email}
											<div class="mt-3 grid gap-2 text-xs text-fg-3">
												{#if selectedListing.broker?.logo_url}
													<img
														src={selectedListing.broker.logo_url}
														alt=""
														loading="lazy"
														decoding="async"
														referrerpolicy="no-referrer"
														class="h-9 max-w-28 rounded border border-border bg-white object-contain p-1"
														onerror={hideBrokenImage}
													/>
												{/if}
												{#if selectedListing.broker?.phone}
													<p>{selectedListing.broker.phone}</p>
												{/if}
												{#if selectedListing.broker?.email}
													<p class="truncate">{selectedListing.broker.email}</p>
												{/if}
											</div>
										{/if}
									</div>
								</div>

								{#if selectedListing.floorplans?.length}
									<div>
										<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
											<DraftingCompass size={15} strokeWidth={2} />
											Floorplan
										</h3>
										{#each selectedListing.floorplans.slice(0, 2) as floorplan, index (`${floorplan.image_url}-${index}`)}
											<div class="overflow-hidden rounded-md border border-border bg-panel">
												{#if floorplan.image_url}
													<img
														src={floorplan.image_url}
														alt=""
														loading="lazy"
														decoding="async"
														referrerpolicy="no-referrer"
														class="max-h-64 w-full object-contain"
														onerror={hideBrokenImage}
													/>
												{/if}
												<div class="flex items-center justify-between gap-3 px-3 py-2 text-xs text-fg-3">
													<span>{floorplan.dimension ?? 'Floorplan'}</span>
													<span>{floorplan.area_sqft ? `${Math.round(floorplan.area_sqft).toLocaleString()} sqft` : ''}</span>
												</div>
											</div>
										{/each}
									</div>
								{/if}

								<div>
									<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
										<Building2 size={15} strokeWidth={2} />
										Details
									</h3>
									<div class="grid grid-cols-2 gap-2 text-sm">
										<div class="rounded-md bg-panel px-3 py-2">
											<p class="text-[11px] text-fg-4">Listed</p>
											<p class="mt-1 font-semibold text-fg-1">{formatDate(selectedListing.listed_date)}</p>
										</div>
										<div class="rounded-md bg-panel px-3 py-2">
											<p class="text-[11px] text-fg-4">Furnished</p>
											<p class="mt-1 font-semibold text-fg-1">{selectedListing.furnished ?? '-'}</p>
										</div>
										<div class="rounded-md bg-panel px-3 py-2">
											<p class="text-[11px] text-fg-4">RERA</p>
											<p class="mt-1 truncate font-semibold text-fg-1">{selectedListing.rera ?? '-'}</p>
										</div>
										<div class="rounded-md bg-panel px-3 py-2">
											<p class="text-[11px] text-fg-4">Status</p>
											<p class="mt-1 font-semibold text-fg-1">{selectedListing.completion_status ?? '-'}</p>
										</div>
									</div>
								</div>

								{#if selectedListing.amenities?.length}
									<div>
										<h3 class="mb-2 flex items-center gap-2 text-sm font-semibold text-fg-1">
											<ShieldCheck size={15} strokeWidth={2} />
											Amenities
										</h3>
										<div class="flex flex-wrap gap-1.5">
											{#each selectedListing.amenities.slice(0, 14) as amenity (amenity)}
												<span class="rounded-full bg-info-bg px-2 py-1 text-[11px] font-medium text-info">
													{amenity}
												</span>
											{/each}
										</div>
									</div>
								{/if}

							{/if}
						</div>
					{/if}
				</div>
			</aside>
		</section>
	</PageContainer>
</AppFrame>
