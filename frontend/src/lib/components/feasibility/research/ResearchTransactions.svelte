<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { transactions } from '$lib/api/transactions'
import { feasibilityStore } from '$lib/stores/feasibility.svelte'
import { researchPanelStore } from '$lib/stores/researchPanel.svelte'

function fmtK(n: number | null): string {
	if (n === null || n === undefined) return '—'
	const k = Math.round(Math.abs(n) / 1000)
	return k.toLocaleString('en-AE')
}

function fmtDate(d: string | null): string {
	if (!d) return '—'
	return new Date(d).toLocaleDateString('en-AE', {
		day: 'numeric',
		month: 'short',
		year: '2-digit'
	})
}

function truncate(s: string | null, n = 20): string {
	if (!s) return '—'
	return s.length > n ? `${s.slice(0, n)}…` : s
}

const area = $derived(feasibilityStore.area ?? '')
const agentData = $derived(researchPanelStore.agentTransactions)
const filters = $derived(researchPanelStore.txFilters)

const UNIT_TYPES = ['', 'Studio', '1BR', '2BR', '3BR', '4BR']
const DAY_OPTIONS = [90, 180, 365, 730]

// TanStack Query — only active when no agent data
const query = createQuery(() => ({
	queryKey: ['res-tx', area, filters.unitType, filters.days] as const,
	queryFn: () =>
		transactions.sales({
			area,
			rooms: filters.unitType || undefined,
			timeframe_days: filters.days,
			limit: 50,
			trans_group: 'Sales'
		}),
	enabled: !!area && !agentData,
	staleTime: 5 * 60_000
}))

const rows = $derived(agentData ? agentData.rows : (query.data?.transactions ?? []))
</script>

<div class="flex flex-col h-full min-h-0">
	<!-- Agent badge -->
	{#if agentData}
		<div
			class="px-2 py-1.5 bg-teal-50 border-b border-teal-100 text-[10px] text-teal-700 font-medium flex-shrink-0"
		>
			Agent view — {agentData.filters.area || area}
			{#if agentData.filters.unit_type}
				· {agentData.filters.unit_type}{/if}
			· {agentData.count} results
		</div>
	{:else}
		<!-- Filter row -->
		<div class="flex items-center gap-1.5 px-2 py-1.5 border-b border-slate-100 flex-shrink-0">
			<select
				class="text-[10px] border border-slate-200 rounded px-1.5 py-0.5 text-slate-600 bg-white"
				value={filters.unitType}
				onchange={(e) =>
					researchPanelStore.setTxFilter({ unitType: (e.target as HTMLSelectElement).value })}
			>
				{#each UNIT_TYPES as t (t)}
					<option value={t}>{t || 'All types'}</option>
				{/each}
			</select>
			<select
				class="text-[10px] border border-slate-200 rounded px-1.5 py-0.5 text-slate-600 bg-white"
				value={filters.days}
				onchange={(e) =>
					researchPanelStore.setTxFilter({ days: Number((e.target as HTMLSelectElement).value) })}
			>
				{#each DAY_OPTIONS as d (d)}
					<option value={d}>{d}d</option>
				{/each}
			</select>
		</div>
	{/if}

	<!-- Table -->
	<div class="flex-1 overflow-y-auto scrollbar-hide min-h-0">
		{#if !agentData && query.isPending}
			<!-- Skeleton -->
			<div class="space-y-px">
				{#each Array(8) as _, i (`tx-skeleton-${i}`)}
					<div class="flex gap-1 px-2 py-1.5 animate-pulse">
						<div class="h-3 bg-slate-100 rounded flex-1"></div>
						<div class="h-3 bg-slate-100 rounded w-14"></div>
						<div class="h-3 bg-slate-100 rounded w-8"></div>
						<div class="h-3 bg-slate-100 rounded w-10"></div>
					</div>
				{/each}
			</div>
		{:else if rows.length === 0}
			<div
				class="flex items-center justify-center h-full text-[11px] text-slate-400 text-center px-4"
			>
				No transactions found{area ? ` for ${area}` : ''}.
			</div>
		{:else}
			<table class="w-full text-[10px] border-collapse">
				<thead class="sticky top-0 bg-slate-50 z-10">
					<tr class="border-b border-slate-200">
						<th class="text-left px-2 py-1 text-slate-400 font-medium">Date</th>
						<th class="text-left px-1 py-1 text-slate-400 font-medium">Project</th>
						<th class="text-left px-1 py-1 text-slate-400 font-medium">Type</th>
						<th class="text-right px-1 py-1 text-slate-400 font-medium">sqm</th>
						<th class="text-right px-2 py-1 text-slate-400 font-medium">/sqm</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as row (`${row.instance_date}-${row.project_name}-${row.actual_worth}`)}
						{@const r = row as Record<string, unknown>}
						<tr class="border-b border-slate-50 hover:bg-slate-50/60">
							<td class="px-2 py-1 text-slate-500 whitespace-nowrap"
								>{fmtDate(r.instance_date as string)}</td
							>
							<td class="px-1 py-1 text-slate-700 max-w-[80px] truncate"
								>{truncate(r.project_name_en as string)}</td
							>
							<td class="px-1 py-1 text-slate-500 whitespace-nowrap">{r.rooms_en ?? '—'}</td>
							<td class="px-1 py-1 text-right text-slate-700 tabular-nums"
								>{r.procedure_area ? Math.round(r.procedure_area as number) : '—'}</td
							>
							<td class="px-2 py-1 text-right text-slate-700 tabular-nums"
								>{fmtK(r.meter_sale_price as number)}k</td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>
