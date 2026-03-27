<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'

function fmt(value: number | null | undefined, digits = 0) {
	if (value === null || value === undefined || !Number.isFinite(value)) return '0'
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

const outputs = $derived(workbookStore.outputs)
const validation = $derived(workbookStore.validation)
const hardFailures = $derived(validation?.hardFailures ?? 0)
const warnings = $derived(validation?.warnings ?? 0)
const missingEvidence = $derived(validation?.missingEvidence ?? 0)

function hasIssue(code: string) {
	return (validation?.issues ?? []).some((issue) => issue.code === code)
}

type CheckStatus = 'within_range' | 'warning' | 'outlier' | 'missing'

function pill(status: CheckStatus) {
	if (status === 'outlier') return 'bg-rose-100 text-rose-700'
	if (status === 'warning') return 'bg-amber-100 text-amber-700'
	if (status === 'missing') return 'bg-slate-200 text-slate-600'
	return 'bg-emerald-100 text-emerald-700'
}

const modelChecks = $derived([
	{
		label: 'Sources vs uses',
		value: outputs ? `Gap AED ${fmt(outputs.funding.gapAed)}` : 'N/A',
		status: !outputs ? 'missing' : hasIssue('funding_gap') ? 'warning' : 'within_range',
		note: 'Model should reconcile tightly before sign-off across funding and uses summaries'
	},
	{
		label: 'Total costs',
		value: outputs ? `AED ${fmt(outputs.costs.totalCostsInclVatAed)}` : 'N/A',
		status: !outputs ? 'missing' : 'within_range',
		note: 'Total project costs including VAT'
	},
	{
		label: 'Gross margin',
		value: outputs ? `${fmt(outputs.returns.grossMarginPct, 1)}%` : 'N/A',
		status: !outputs
			? 'missing'
			: outputs.returns.grossMarginPct < 0
				? 'outlier'
				: outputs.returns.grossMarginPct < 10
					? 'warning'
					: 'within_range',
		note: 'Gross margin should be positive and reasonable'
	},
	{
		label: 'Project IRR',
		value:
			outputs?.returns?.projectIrrPct != null ? `${fmt(outputs.returns.projectIrrPct, 1)}%` : 'N/A',
		status:
			outputs?.returns?.projectIrrPct == null
				? 'missing'
				: outputs.returns.projectIrrPct < 0
					? 'outlier'
					: outputs.returns.projectIrrPct > 30
						? 'warning'
						: 'within_range',
		note: 'Check for implausible or broken timed cash flows'
	},
	{
		label: 'Unit count',
		value: outputs ? `${fmt(outputs.program.totalUnits)} units` : 'N/A',
		status: !outputs ? 'missing' : outputs.program.totalUnits === 0 ? 'warning' : 'within_range',
		note: 'At least one unit type should be configured'
	}
] satisfies Array<{ label: string; value: string; status: CheckStatus; note: string }>)
</script>

{#if !outputs || !validation}
<div class="h-full flex items-center justify-center px-6 text-sm text-slate-400">
Generate an HBU study to build the draft checks view.
</div>
{:else}
<div class="h-full overflow-auto">
<div class="px-4 py-4 space-y-4">
<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
<div class="rounded-xl border border-slate-200 px-4 py-3">
<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Validation status</p>
<p class="text-base font-semibold text-slate-900 mt-1">{validation.status.replace('_', ' ')}</p>
<p class="text-[11px] text-slate-400 mt-1">Workbook underwriting checks</p>
</div>
<div class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
<p class="text-[11px] uppercase tracking-[0.12em] text-rose-500">Hard fails</p>
<p class="text-base font-semibold text-rose-700 mt-1">{fmt(hardFailures)}</p>
</div>
<div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
<p class="text-[11px] uppercase tracking-[0.12em] text-amber-500">Warnings</p>
<p class="text-base font-semibold text-amber-700 mt-1">{fmt(warnings)}</p>
</div>
<div class="rounded-xl border border-slate-200 px-4 py-3">
<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">Missing evidence</p>
<p class="text-base font-semibold text-slate-900 mt-1">{fmt(missingEvidence)}</p>
</div>
</div>

<div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
{#each modelChecks as check (check.label)}
<div class="rounded-xl border border-slate-200 px-4 py-3">
<div class="flex items-center justify-between gap-2">
<p class="text-[11px] uppercase tracking-[0.12em] text-slate-400">{check.label}</p>
<span class="text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-[0.12em] {pill(check.status)}">
{check.status.replace('_', ' ')}
</span>
</div>
<p class="text-base font-semibold text-slate-900 mt-2">{check.value}</p>
<p class="text-[11px] text-slate-400 mt-1">{check.note}</p>
</div>
{/each}
</div>

<div class="rounded-xl border border-slate-200 overflow-hidden">
<div class="grid grid-cols-[120px_140px_1fr] gap-3 px-4 py-3 bg-slate-50 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400">
<span>Severity</span>
<span>Code</span>
<span>Message</span>
</div>
{#if validation.issues.length}
{#each validation.issues as issue (`${issue.code}-${issue.field ?? ''}`)}
<div class="grid grid-cols-[120px_140px_1fr] gap-3 px-4 py-3 border-t border-slate-100 text-sm">
<span class="font-medium {issue.severity === 'hard_fail' ? 'text-rose-700' : issue.severity === 'warning' ? 'text-amber-700' : 'text-slate-500'}">
{issue.severity.replace('_', ' ')}
</span>
<span class="text-slate-500">{issue.code}</span>
<div>
<p class="text-slate-800">{issue.message}</p>
{#if issue.field}
<p class="text-[11px] text-slate-400 mt-1">Field: {issue.field}</p>
{/if}
</div>
</div>
{/each}
{:else}
<div class="px-4 py-4 text-sm text-slate-500">
No validation issues were returned on the current draft.
</div>
{/if}
</div>
</div>
</div>
{/if}
