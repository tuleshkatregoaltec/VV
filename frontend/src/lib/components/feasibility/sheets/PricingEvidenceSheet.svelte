<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

const study = $derived(
	workbookStore.research
		? {
				market_area: workbookStore.research.market_area,
				usage: workbookStore.research.usage,
				headline: workbookStore.study_context?.headline || workbookStore.research.headline,
				off_plan_unit_benchmarks: workbookStore.research.off_plan_unit_benchmarks,
				market_pricing: workbookStore.research.market_pricing,
				pricing_evidence: workbookStore.research.pricing_evidence,
				competition_evidence: workbookStore.research.competition_evidence,
				land_sales_evidence: workbookStore.research.land_sales_evidence
			}
		: null
)

const outputs = $derived(workbookStore.outputs)
const assumptions = $derived(workbookStore.assumptions)
const programRows = $derived(outputs?.program.rows ?? [])

function fmt(n: number, digits = 0): string {
	return n.toLocaleString('en-AE', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function rateToSqft(aedPerSqm: number) {
	return aedPerSqm * 0.092903
}
function toSqft(sqm: number) {
	return sqm / 0.092903
}

const confidenceBadge: Record<string, string> = {
	high: 'bg-emerald-100 text-emerald-700',
	medium: 'bg-amber-100 text-amber-700',
	low: 'bg-rose-100 text-rose-700'
}

const HEADER = 'bg-[#1F3864] text-white px-2 py-[4px] font-bold text-[11px] tracking-wide'
const SUBHEADER =
	'bg-[#D6DCE4] px-2 py-[3px] text-slate-700 font-semibold text-[10px] tracking-wider uppercase'
const TH =
	'px-2 py-[4px] text-right text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-b border-[#B8C4CE] bg-[#EEF2F7]'
const TH_LEFT =
	'px-2 py-[4px] text-left text-[10px] font-semibold text-slate-600 uppercase tracking-wider border-b border-[#B8C4CE] bg-[#EEF2F7]'
const TD = 'px-2 py-[3px] text-right tabular-nums text-slate-800 border-b border-[#EBEBEB]'
const TD_LEFT = 'px-2 py-[3px] text-left text-slate-800 border-b border-[#EBEBEB]'
</script>

<div class="overflow-auto flex-1 bg-white text-[11px] font-[Calibri,'Segoe_UI',Arial,sans-serif]">

	<!-- Header -->
	<div class="bg-[#1F3864] text-white px-4 py-2.5 flex items-start justify-between gap-4">
		<div>
			<div class="text-[13px] font-bold tracking-wide">PRICING EVIDENCE</div>
			<div class="text-[10px] text-blue-200 mt-0.5">
				{study ? `${study.market_area} — Off-plan & market pricing comparables` : 'Load a plot to populate pricing evidence'}
			</div>
		</div>
	</div>

	{#if !study}
		<div class="flex items-center justify-center h-40 text-slate-400 text-xs">
			No HBU study loaded. Run a study from the chat assistant to populate this sheet.
		</div>
	{:else}
		<!-- ═══ SUBJECT PROPERTY SUMMARY ═══ -->
		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>
				<tr><td colspan="8" class={HEADER}>SUBJECT PROPERTY SUMMARY</td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:25%"><col style="width:25%"><col style="width:25%"><col style="width:25%">
			</colgroup>
			<tbody>
				<tr>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Market Area</td>
					<td class="{TD_LEFT} border-r border-[#E8E8E8] font-medium">{study.market_area}</td>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Usage</td>
					<td class={TD_LEFT}>{study.usage.replace('_', ' ')}</td>
				</tr>
				<tr>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Plot Area (sqm)</td>
					<td class="{TD_LEFT} border-r border-[#E8E8E8]">{outputs ? fmt(outputs.area.plotAreaSqm) : fmt(assumptions?.plotAreaSqm ?? 0)}</td>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Max GFA (sqm)</td>
					<td class={TD_LEFT}>{outputs ? fmt(outputs.area.maxGfaSqm) : '—'}</td>
				</tr>
				<tr>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Total Units</td>
					<td class="{TD_LEFT} border-r border-[#E8E8E8]">{outputs ? fmt(outputs.program.totalUnits, 0) : '0'}</td>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Parking Spaces</td>
					<td class={TD_LEFT}>{fmt(outputs?.program.totalParkingSpaces ?? 0, 0)}</td>
				</tr>
				<tr>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Wtd. Avg Price (AED/sqft)</td>
					<td class="{TD_LEFT} border-r border-[#E8E8E8] font-medium text-[#1565C0]">
						{outputs ? fmt(rateToSqft(outputs.program.weightedAvgSalesRatePsqm)) : '—'}
					</td>
					<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">Gross Revenue (AED)</td>
					<td class="{TD_LEFT} font-medium">{outputs ? fmt(outputs.program.grossRevenueAed) : '0'}</td>
				</tr>
				{#if study.headline}
					<tr>
						<td class="{TD_LEFT} font-semibold text-slate-500 text-[10px] uppercase tracking-wide border-r border-[#E8E8E8]">HBU Headline</td>
						<td colspan="3" class="{TD_LEFT} italic text-slate-600">{study.headline}</td>
					</tr>
				{/if}
			</tbody>
		</table>

		<!-- Unit mix from program -->
		{#if outputs && programRows.length > 0}
		<table class="w-full border-collapse mt-0" style="border-spacing:0">
			<tbody><tr><td colspan="6" class={SUBHEADER}>Unit Configuration Mix</td></tr></tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:20%"><col style="width:13%"><col style="width:13%"><col style="width:18%"><col style="width:18%"><col style="width:18%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Unit Type</th>
					<th class="{TH} border-r border-[#D9D9D9]">Units</th>
					<th class="{TH} border-r border-[#D9D9D9]">Share %</th>
					<th class="{TH} border-r border-[#D9D9D9]">Avg Size (sqft)</th>
					<th class="{TH} border-r border-[#D9D9D9]">AED/sqft</th>
					<th class={TH}>Gross Revenue</th>
				</tr>
			</thead>
			<tbody>
				{#each programRows as row}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{row.label}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(row.units)}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{outputs.program.totalUnits > 0 ? ((row.units / outputs.program.totalUnits) * 100).toFixed(1) : '0.0'}%</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(toSqft(row.avgSizeSqm))}</td>
						<td class="{TD} border-r border-[#E8E8E8] text-[#1565C0] font-semibold">{fmt(rateToSqft(row.sellingRatePsqm))}</td>
						<td class={TD}>{fmt(row.revenueAed)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		<!-- ═══ SECTION 1: OFF-PLAN UNIT BENCHMARKS ═══ -->
		{#if (study.off_plan_unit_benchmarks?.length ?? 0) > 0}
		<table class="w-full border-collapse" style="border-spacing:0">
			<tbody>
				<tr><td colspan="8" class={HEADER}>1. &nbsp; OFF-PLAN PRICING BENCHMARKS <span class="text-blue-300 font-normal text-[10px]">(selected horizon per unit type)</span></td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:14%">
				<col style="width:13%">
				<col style="width:10%">
				<col style="width:10%">
				<col style="width:12%">
				<col style="width:12%">
				<col style="width:12%">
				<col style="width:17%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Unit Type</th>
					<th class="{TH} border-r border-[#D9D9D9]">Horizon</th>
					<th class="{TH} border-r border-[#D9D9D9]">Avg Months</th>
					<th class="{TH} border-r border-[#D9D9D9]">Txn Count</th>
					<th class="{TH} border-r border-[#D9D9D9]">Median AED/sqm</th>
					<th class="{TH} border-r border-[#D9D9D9]">Median AED/sqft</th>
					<th class="{TH} border-r border-[#D9D9D9]">Confidence</th>
					<th class={TH}>Last Transaction</th>
				</tr>
			</thead>
			<tbody>
				{#each study.off_plan_unit_benchmarks ?? [] as b}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{b.unit_type}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{b.selected_horizon_bucket}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(b.avg_months_to_completion, 0)}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(b.transaction_count)}</td>
						<td class="{TD} border-r border-[#E8E8E8] font-semibold">{fmt(b.selected_price_sqm)}</td>
						<td class="{TD} border-r border-[#E8E8E8] font-semibold text-[#1565C0]">{fmt(rateToSqft(b.selected_price_sqm))}</td>
						<td class="px-2 py-[3px] border-r border-[#E8E8E8] border-b border-[#EBEBEB]">
							<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide {confidenceBadge[b.confidence_label] ?? ''}">
								{b.confidence_label}
							</span>
						</td>
						<td class="{TD} text-slate-500">{b.last_transaction_date?.slice(0, 10) ?? '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		<!-- ═══ SECTION 2: MARKET PRICING (COMPLETED TRANSACTIONS) ═══ -->
		{#if (study.market_pricing?.length ?? 0) > 0}
		<table class="w-full border-collapse mt-0" style="border-spacing:0">
			<tbody>
				<tr><td colspan="5" class={HEADER}>2. &nbsp; MARKET PRICING <span class="text-blue-300 font-normal text-[10px]">(completed transaction medians)</span></td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:20%">
				<col style="width:20%">
				<col style="width:20%">
				<col style="width:20%">
				<col style="width:20%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Unit Type</th>
					<th class="{TH} border-r border-[#D9D9D9]">Transactions</th>
					<th class="{TH} border-r border-[#D9D9D9]">Median AED/sqm</th>
					<th class="{TH} border-r border-[#D9D9D9]">Median AED/sqft</th>
					<th class={TH}>Avg Area (sqft)</th>
				</tr>
			</thead>
			<tbody>
				{#each study.market_pricing ?? [] as row}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{row.unit_type}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(row.transaction_count)}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(row.median_price_sqm)}</td>
						<td class="{TD} border-r border-[#E8E8E8] font-semibold text-[#1565C0]">{fmt(rateToSqft(row.median_price_sqm))}</td>
						<td class={TD}>{row.avg_area_sqm ? fmt(toSqft(row.avg_area_sqm)) : '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		<!-- ═══ SECTION 3: COMPARABLE PROJECTS ═══ -->
		{#if (study.pricing_evidence?.length ?? 0) > 0}
		<table class="w-full border-collapse mt-0" style="border-spacing:0">
			<tbody>
				<tr><td colspan="7" class={HEADER}>3. &nbsp; COMPARABLE PROJECTS <span class="text-blue-300 font-normal text-[10px]">(off-plan sales comps)</span></td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:22%">
				<col style="width:14%">
				<col style="width:8%">
				<col style="width:8%">
				<col style="width:10%">
				<col style="width:14%">
				<col style="width:24%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Project</th>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Area</th>
					<th class="{TH} border-r border-[#D9D9D9]">Buildings</th>
					<th class="{TH} border-r border-[#D9D9D9]">Units</th>
					<th class="{TH} border-r border-[#D9D9D9]">AED/sqft</th>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Dom. Type</th>
					<th class={TH_LEFT}>Rationale</th>
				</tr>
			</thead>
			<tbody>
				{#each study.pricing_evidence ?? [] as comp}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{comp.project_name}</td>
						<td class="{TD_LEFT} text-slate-500 border-r border-[#E8E8E8]">{comp.area_name}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{comp.no_of_buildings ?? '—'}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{comp.no_of_units != null ? fmt(comp.no_of_units) : '—'}</td>
						<td class="{TD} border-r border-[#E8E8E8] font-semibold text-[#1565C0]">
							{comp.median_price_sqm != null ? fmt(rateToSqft(comp.median_price_sqm)) : '—'}
						</td>
						<td class="{TD_LEFT} text-slate-600 border-r border-[#E8E8E8]">{comp.dominant_unit_type ?? '—'}</td>
						<td class="px-2 py-[3px] text-slate-500 border-b border-[#EBEBEB] text-[9px] leading-relaxed">
							{(comp.rationale ?? []).join(' · ')}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		<!-- ═══ SECTION 4: COMPETITION / PIPELINE ═══ -->
		{#if (study.competition_evidence?.length ?? 0) > 0}
		<table class="w-full border-collapse mt-0" style="border-spacing:0">
			<tbody>
				<tr><td colspan="6" class={HEADER}>4. &nbsp; COMPETITION &amp; PIPELINE <span class="text-blue-300 font-normal text-[10px]">(comparable projects under development)</span></td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:22%"><col style="width:14%"><col style="width:8%"><col style="width:8%"><col style="width:10%"><col style="width:38%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Project</th>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Area</th>
					<th class="{TH} border-r border-[#D9D9D9]">Status</th>
					<th class="{TH} border-r border-[#D9D9D9]">Units</th>
					<th class="{TH} border-r border-[#D9D9D9]">Score</th>
					<th class={TH_LEFT}>Rationale</th>
				</tr>
			</thead>
			<tbody>
				{#each study.competition_evidence ?? [] as comp}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{comp.project_name}</td>
						<td class="{TD_LEFT} text-slate-500 border-r border-[#E8E8E8]">{comp.area_name}</td>
						<td class="{TD_LEFT} text-slate-500 border-r border-[#E8E8E8] text-[10px]">{comp.project_status ?? '—'}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{comp.no_of_units != null ? fmt(comp.no_of_units) : '—'}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{comp.score.toFixed(0)}</td>
						<td class="px-2 py-[3px] text-slate-500 border-b border-[#EBEBEB] text-[9px] leading-relaxed">{(comp.rationale ?? []).join(' · ')}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		<!-- ═══ SECTION 5: LAND MARKET EVIDENCE ═══ -->
		{#if (study.land_sales_evidence?.length ?? 0) > 0}
		<table class="w-full border-collapse mt-0" style="border-spacing:0">
			<tbody>
				<tr><td colspan="7" class={HEADER}>5. &nbsp; LAND MARKET EVIDENCE <span class="text-blue-300 font-normal text-[10px]">(registered land transactions)</span></td></tr>
			</tbody>
		</table>
		<table class="w-full border-collapse border-b border-[#D9D9D9]" style="border-spacing:0">
			<colgroup>
				<col style="width:11%"><col style="width:16%"><col style="width:14%"><col style="width:13%"><col style="width:13%"><col style="width:13%"><col style="width:20%">
			</colgroup>
			<thead>
				<tr>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Date</th>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Area</th>
					<th class="{TH_LEFT} border-r border-[#D9D9D9]">Usage</th>
					<th class="{TH} border-r border-[#D9D9D9]">Plot Area (sqm)</th>
					<th class="{TH} border-r border-[#D9D9D9]">Price (AED)</th>
					<th class="{TH} border-r border-[#D9D9D9]">AED/sqm</th>
					<th class={TH_LEFT}>Landmark</th>
				</tr>
			</thead>
			<tbody>
				{#each study.land_sales_evidence ?? [] as lse}
					<tr class="hover:bg-slate-50/60">
						<td class="{TD_LEFT} text-slate-500 border-r border-[#E8E8E8]">{lse.instance_date?.slice(0, 10) ?? '—'}</td>
						<td class="{TD_LEFT} font-medium border-r border-[#E8E8E8]">{lse.area_name}</td>
						<td class="{TD_LEFT} text-slate-500 border-r border-[#E8E8E8] text-[10px]">{lse.property_usage}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(lse.plot_area_sqm)}</td>
						<td class="{TD} border-r border-[#E8E8E8]">{fmt(lse.price_aed)}</td>
						<td class="{TD} border-r border-[#E8E8E8] font-semibold text-[#1565C0]">{fmt(lse.price_sqm)}</td>
						<td class="{TD_LEFT} text-slate-400 text-[10px]">{lse.nearest_landmark ?? '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{/if}

		{#if (study.off_plan_unit_benchmarks?.length ?? 0) === 0 && (study.market_pricing?.length ?? 0) === 0 && (study.pricing_evidence?.length ?? 0) === 0}
			<div class="flex items-center justify-center h-32 text-slate-400 text-xs">
				No pricing evidence in this study. The agent may not have run pricing comparables yet.
			</div>
		{/if}

		<!-- bottom padding -->
		<div class="py-4"></div>
	{/if}
</div>
