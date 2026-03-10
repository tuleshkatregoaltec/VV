<script lang="ts">
import { feasibility } from '$lib/api/feasibility'
import type { GISPlotDossier, HBUStudy } from '$lib/stores/feasibility.svelte'

let {
	dossier,
	onApply
}: {
	dossier: GISPlotDossier
	onApply: (study: HBUStudy) => void
} = $props()

let study = $state<HBUStudy | null>(null)
let loading = $state(false)
let error = $state('')
let lastGeneratedPlot = $state('')

function fmt(n: number) {
	return n.toLocaleString('en-AE', { maximumFractionDigits: 0 })
}

async function generate() {
	error = ''
	lastGeneratedPlot = dossier.plot_number
	loading = true
	try {
		study = await feasibility.generateHBUStudy(dossier.plot_number, dossier.inferred_usage)
	} catch (err) {
		error = err instanceof Error ? err.message : 'Failed to generate the HBU study.'
	} finally {
		loading = false
	}
}

$effect(() => {
	if (dossier.plot_number && lastGeneratedPlot !== dossier.plot_number && !loading) {
		generate()
	}
})
</script>

<div class="max-w-5xl mx-auto">
	<div class="flex items-start justify-between gap-4 mb-6">
		<div>
			<h2 class="text-xl font-semibold text-slate-800 mb-1">Plot review and initial HBU study</h2>
			<p class="text-sm text-slate-500">
				The study is generated automatically from the GIS plot dossier using the inferred zoning and
				use constraints.
			</p>
		</div>
		<div class="flex items-center gap-2">
			<button
				type="button"
				class="px-4 py-2.5 rounded-xl bg-teal-600 text-white font-medium text-sm hover:bg-teal-700 disabled:opacity-50 transition-colors"
				onclick={generate}
				disabled={loading}
			>
				{loading ? 'Generating…' : 'Regenerate study'}
			</button>
		</div>
	</div>

	<div class="grid gap-4 lg:grid-cols-[1.05fr_0.95fr] mb-4">
		<div class="rounded-2xl border border-slate-200 bg-white p-5">
			<div class="flex items-start justify-between gap-3 mb-4">
				<div>
					<p class="text-xs font-medium tracking-[0.14em] uppercase text-slate-400">
						{dossier.community_name}
					</p>
					<h3 class="text-lg font-semibold text-slate-900 mt-1">{dossier.plot_number}</h3>
					{#if dossier.project_name}
						<p class="text-sm text-slate-500 mt-1">{dossier.project_name}</p>
					{/if}
				</div>
				<span
					class="px-2.5 py-1 rounded-full text-xs font-medium {dossier.is_verified
						? 'bg-emerald-100 text-emerald-700'
						: 'bg-amber-100 text-amber-700'}"
				>
					{dossier.is_verified ? 'Verified GIS record' : 'Unverified GIS record'}
				</span>
			</div>

			<div class="grid gap-3 sm:grid-cols-2">
				<div class="rounded-xl bg-slate-50 px-4 py-3">
					<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Plot area</p>
					<p class="text-base font-semibold text-slate-900 mt-1">
						{fmt(dossier.plot_area_sqm)} sqm
					</p>
				</div>
				<div class="rounded-xl bg-slate-50 px-4 py-3">
					<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Maximum GFA</p>
					<p class="text-base font-semibold text-slate-900 mt-1">
						{dossier.max_gfa_sqm > 0 ? `${fmt(dossier.max_gfa_sqm)} sqm` : 'Not available'}
					</p>
				</div>
				<div class="rounded-xl bg-slate-50 px-4 py-3">
					<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Maximum height</p>
					<p class="text-base font-semibold text-slate-900 mt-1">
						{dossier.max_height || 'Not available'}
					</p>
				</div>
				<div class="rounded-xl bg-slate-50 px-4 py-3">
					<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Derived FAR</p>
					<p class="text-base font-semibold text-slate-900 mt-1">
						{dossier.far ?? 'Not available'}
					</p>
				</div>
			</div>

			<div class="mt-5">
				<p class="text-sm font-semibold text-slate-800 mb-2">GIS restrictions</p>
				<div class="flex flex-wrap gap-2 mb-3">
					<span class="px-2.5 py-1 rounded-full bg-teal-100 text-teal-700 text-xs font-medium">
						Inferred usage: {dossier.inferred_usage}
					</span>
					{#if dossier.gfa_type}
						<span class="px-2.5 py-1 rounded-full bg-blue-100 text-blue-700 text-xs font-medium"
							>{dossier.gfa_type}</span
						>
					{/if}
					{#if dossier.max_coverage}
						<span class="px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 text-xs font-medium"
							>Coverage {dossier.max_coverage}</span
						>
					{/if}
				</div>
				{#if dossier.land_use.length > 0}
					<div class="rounded-xl border border-slate-200 overflow-hidden text-sm">
						{#each dossier.land_use as item, idx (`${item.type}-${item.use}-${idx}`)}
							<div
								class="flex items-center justify-between px-3 py-2 {idx <
								dossier.land_use.length - 1
									? 'border-b border-slate-100'
									: ''}"
							>
								<span class="text-slate-500">{item.type}</span>
								<span class="font-medium text-slate-800">{item.use}</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div class="space-y-4">
			<div class="rounded-2xl border border-slate-200 bg-white p-5">
				<p class="text-sm font-semibold text-slate-800 mb-3">General notes</p>
				{#if dossier.general_notes.length === 0}
					<p class="text-sm text-slate-400">No general notes on the GIS record.</p>
				{:else}
					<ul class="space-y-2 text-sm text-slate-600 list-disc pl-5">
						{#each dossier.general_notes as note, idx (`${note}-${idx}`)}
							<li>{note}</li>
						{/each}
					</ul>
				{/if}
			</div>

			<div class="rounded-2xl border border-amber-200 bg-amber-50 p-5">
				<p class="text-sm font-semibold text-amber-800 mb-3">Model seeding note</p>
				<p class="text-sm text-amber-700 leading-relaxed">
					The workspace now applies the HBU as a conservative first pass. Land cost, build cost, and
					timing are seeded with safer defaults and still need manual review.
				</p>
			</div>
		</div>
	</div>

	{#if error}
		<div class="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
			{error}
		</div>
	{/if}

	{#if loading && !study}
		<div class="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center">
			<div
				class="w-5 h-5 border-2 border-teal-500 border-t-transparent rounded-full animate-spin mx-auto"
			></div>
			<p class="text-sm font-medium text-slate-700 mt-4">Generating initial HBU study…</p>
			<p class="text-sm text-slate-400 mt-1">
				Pulling plot constraints, pricing evidence, and comparable projects.
			</p>
		</div>
	{:else if !study}
		<div
			class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center"
		>
			<p class="text-sm font-medium text-slate-600">No HBU study generated yet.</p>
			<p class="text-sm text-slate-400 mt-1">
				Regenerate the study if needed, then seed the workspace from it.
			</p>
		</div>
	{:else}
		<div class="space-y-4">
			<div class="rounded-2xl border border-slate-200 bg-white p-5">
				<p class="text-xs font-medium tracking-[0.14em] uppercase text-slate-400">
					{study.market_area}
				</p>
				<h3 class="text-lg font-semibold text-slate-900 mt-1">{study.headline}</h3>
				<ul class="mt-3 space-y-2 text-sm text-slate-600 list-disc pl-5">
					{#each study.summary as item, idx (`summary-${idx}`)}
						<li>{item}</li>
					{/each}
				</ul>
			</div>

			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-2xl border border-slate-200 bg-white p-5">
					<p class="text-sm font-semibold text-slate-800 mb-3">Constraints</p>
					<ul class="space-y-2 text-sm text-slate-600 list-disc pl-5">
						{#each study.constraints as item, idx (`constraint-${idx}`)}
							<li>{item}</li>
						{/each}
					</ul>
				</div>

				<div class="rounded-2xl border border-slate-200 bg-white p-5">
					<p class="text-sm font-semibold text-slate-800 mb-3">Product options</p>
					<div class="space-y-3">
						{#each study.product_options as option (option.name)}
							<div class="rounded-xl border border-slate-200 px-4 py-3">
								<div class="flex items-start justify-between gap-3">
									<div>
										<p class="font-medium text-slate-900">{option.name}</p>
										<p class="text-sm text-slate-500">{option.positioning}</p>
									</div>
									<span
										class="text-xs font-semibold text-teal-700 bg-teal-100 rounded-full px-2 py-1"
										>Fit {option.fit_score}</span
									>
								</div>
							</div>
						{/each}
					</div>
				</div>
			</div>

			<div class="rounded-2xl border border-slate-200 bg-white p-5">
				<p class="text-sm font-semibold text-slate-800 mb-3">Recommended mix</p>
				<div
					class="grid grid-cols-5 gap-3 text-[11px] font-medium text-slate-400 uppercase tracking-[0.12em] px-3 pb-2"
				>
					<span>Type</span>
					<span class="text-right">Share</span>
					<span class="text-right">Avg size</span>
					<span class="text-right">Price/sqm</span>
					<span class="text-right">Units</span>
				</div>
				<div class="rounded-xl border border-slate-200 overflow-hidden">
					{#each study.recommended_mix as row, idx (`${row.unit_type}-${idx}`)}
						<div
							class="grid grid-cols-5 gap-3 px-3 py-3 text-sm {idx <
							study.recommended_mix.length - 1
								? 'border-b border-slate-100'
								: ''}"
						>
							<span class="font-medium text-slate-800">{row.unit_type}</span>
							<span class="text-right text-slate-600">{row.share_pct}%</span>
							<span class="text-right text-slate-600">{fmt(row.avg_size_sqm)} sqm</span>
							<span class="text-right text-slate-800 font-medium">{fmt(row.price_sqm)}</span>
							<span class="text-right text-slate-600">{row.suggested_units}</span>
						</div>
					{/each}
				</div>
			</div>

			<div class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-2xl border border-slate-200 bg-white p-5">
					<p class="text-sm font-semibold text-slate-800 mb-3">Pricing evidence</p>
					<div class="space-y-3">
						{#each study.pricing_evidence as item, index (`pricing-${item.project_id}-${item.project_name}-${index}`)}
							<div class="rounded-xl border border-slate-200 px-4 py-3">
								<div class="flex items-start justify-between gap-3">
									<div>
										<p class="font-medium text-slate-900">{item.project_name}</p>
										<p class="text-sm text-slate-500">{item.area_name}</p>
									</div>
									<div class="text-right text-sm">
										<p class="font-medium text-slate-800">{item.score}</p>
										{#if item.median_price_sqm}
											<p class="text-slate-500">{fmt(item.median_price_sqm)}/sqm</p>
										{/if}
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>

				<div class="rounded-2xl border border-slate-200 bg-white p-5">
					<p class="text-sm font-semibold text-slate-800 mb-3">Pipeline competition</p>
					<div class="space-y-3">
						{#each study.competition_evidence as item, index (`pipeline-${item.project_id}-${item.project_name}-${index}`)}
							<div class="rounded-xl border border-slate-200 px-4 py-3">
								<div class="flex items-start justify-between gap-3">
									<div>
										<p class="font-medium text-slate-900">{item.project_name}</p>
										<p class="text-sm text-slate-500">{item.project_status || 'Unknown status'}</p>
									</div>
									<p class="text-sm font-medium text-slate-700">{item.score}</p>
								</div>
							</div>
						{/each}
					</div>
				</div>
			</div>

			{#if study.land_sales_evidence.length > 0}
				<div class="rounded-2xl border border-slate-200 bg-white p-5">
					<p class="text-sm font-semibold text-slate-800 mb-3">Land sale evidence</p>
					<div class="space-y-3">
						{#each study.land_sales_evidence as item, index (`land-sale-${item.transaction_id}-${item.instance_date}-${index}`)}
							<div class="rounded-xl border border-slate-200 px-4 py-3">
								<div class="flex items-start justify-between gap-3">
									<div>
										<p class="font-medium text-slate-900">{item.instance_date}</p>
										<p class="text-sm text-slate-500">
											{item.procedure_name || item.project_name || item.area_name}
										</p>
									</div>
									<div class="text-right text-sm">
										<p class="font-medium text-slate-800">{fmt(item.price_sqm)}/sqm</p>
										<p class="text-slate-500">{fmt(item.plot_area_sqm)} sqm</p>
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			{#if study.warnings.length > 0}
				<div class="rounded-2xl border border-amber-200 bg-amber-50 p-5">
					<p class="text-sm font-semibold text-amber-800 mb-3">Warnings</p>
					<ul class="space-y-2 text-sm text-amber-700 list-disc pl-5">
						{#each study.warnings as warning, idx (`warning-${idx}`)}
							<li>{warning}</li>
						{/each}
					</ul>
				</div>
			{/if}

			<div class="flex justify-end">
				<button
					type="button"
					class="px-5 py-3 rounded-xl bg-teal-600 text-white font-medium text-sm hover:bg-teal-700 transition-colors"
					onclick={() => onApply(study)}
				>
					Use this HBU study →
				</button>
			</div>
		</div>
	{/if}
</div>
